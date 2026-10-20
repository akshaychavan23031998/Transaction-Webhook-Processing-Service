import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from redis import Redis
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.v1.transactions import router as transactions_router
from app.api.v1.webhooks import router as webhooks_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.schemas.transaction import HealthResponse, ReadinessResponse

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


def _json_safe(value):
    """Convert validation details into values accepted by JSONResponse."""
    if isinstance(value, BaseException):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("application started", extra={"event": "service.started"})
    yield
    logger.info("application stopped", extra={"event": "service.stopped"})


app = FastAPI(
    title="Transaction Webhook Service",
    version="0.1.0",
    description="Durable, idempotent transaction webhook ingestion and processing.",
    lifespan=lifespan,
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid4()))
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code": "validation_error",
                "message": "Request validation failed",
                "details": _json_safe(exc.errors()),
            }
        },
    )


@app.exception_handler(SQLAlchemyError)
async def database_exception_handler(_: Request, exc: SQLAlchemyError):
    logger.exception("unhandled database error", extra={"event": "database.error"})
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"error": {"code": "dependency_unavailable", "message": "Database unavailable"}},
    )


@app.get("/", response_model=HealthResponse, tags=["health"])
def health() -> HealthResponse:
    return HealthResponse(
        status="HEALTHY",
        current_time=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )


@app.get("/ready", response_model=ReadinessResponse, tags=["health"])
def readiness() -> ReadinessResponse:
    database_status = "READY"
    redis_status = "READY"
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
    except Exception:
        database_status = "NOT_READY"
    try:
        with Redis.from_url(settings.redis_url) as redis_client:
            redis_client.ping()
    except Exception:
        redis_status = "NOT_READY"
    ready = database_status == redis_status == "READY"
    response = ReadinessResponse(
        status="READY" if ready else "NOT_READY", database=database_status, redis=redis_status
    )
    if not ready:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=response.model_dump()
        )
    return response


app.include_router(webhooks_router, prefix="/v1")
app.include_router(transactions_router, prefix="/v1")
