import hashlib
import hmac
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import ConflictingTransactionError, DurableAcceptanceError
from app.db.session import get_db
from app.models.transaction import TransactionStatus
from app.schemas.transaction import TransactionWebhookRequest, WebhookAcceptedResponse
from app.services.transaction_service import TransactionService

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
logger = logging.getLogger(__name__)


def verify_signature(payload: bytes, signature: str | None) -> bool:
    settings = get_settings()
    if not settings.webhook_signature_enabled:
        return True
    if not settings.webhook_signature_secret or not signature:
        return False
    expected = hmac.new(
        settings.webhook_signature_secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


async def get_raw_body(request: Request) -> bytes:
    return await request.body()


@router.post(
    "/transactions",
    response_model=WebhookAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def receive_transaction_webhook(
    payload: TransactionWebhookRequest,
    db: Annotated[Session, Depends(get_db)],
    raw_body: Annotated[bytes, Depends(get_raw_body)],
    x_webhook_signature: Annotated[str | None, Header()] = None,
) -> WebhookAcceptedResponse:
    # Signature verification is intentionally optional for the assessment's sample payload.
    # Provider-specific adapters should verify the raw body before schema processing in production.
    if get_settings().webhook_signature_enabled and not verify_signature(
        raw_body, x_webhook_signature
    ):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        result = TransactionService().accept_webhook(db, payload)
    except ConflictingTransactionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "transaction_payload_conflict", "transaction_id": str(exc)},
        ) from exc
    except DurableAcceptanceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "durable_acceptance_unavailable",
                "message": "Please retry the webhook.",
            },
        ) from exc

    event = "webhook.duplicate" if result.duplicate else "webhook.accepted"
    logger.info(
        "webhook accepted",
        extra={"event": event, "transaction_id": payload.transaction_id},
    )
    return WebhookAcceptedResponse(
        transaction_id=payload.transaction_id,
        status=result.transaction.status or TransactionStatus.PROCESSING,
        duplicate=result.duplicate,
        message="Transaction already accepted" if result.duplicate else "Transaction accepted",
    )
