import logging
import time

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.repositories.transaction_repository import (
    claim_transaction,
    finalize_transaction,
    release_transaction_claim,
)
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="app.workers.tasks.process_transaction",
    max_retries=5,
    default_retry_delay=5,
)
def process_transaction(self, transaction_id: str) -> str:
    settings = get_settings()
    session = SessionLocal()
    claim = None
    try:
        claim = claim_transaction(session, transaction_id)
        if claim is None:
            logger.info(
                "transaction processing skipped because it is already complete or leased",
                extra={"event": "transaction.processing_skipped", "transaction_id": transaction_id},
            )
            return "SKIPPED"

        logger.info(
            "transaction processing started",
            extra={
                "event": "transaction.processing_started",
                "transaction_id": transaction_id,
                "attempt": claim.attempt,
            },
        )
        time.sleep(settings.transaction_processing_delay_seconds)
        finalized = finalize_transaction(session, transaction_id, claim.claim_token)
        if not finalized:
            logger.warning(
                "stale worker could not finalize transaction",
                extra={"event": "transaction.processing_stale", "transaction_id": transaction_id},
            )
            return "STALE"
        logger.info(
            "transaction processing completed",
            extra={"event": "transaction.processing_completed", "transaction_id": transaction_id},
        )
        return "PROCESSED"
    except Exception as exc:
        released = False
        if claim is not None:
            try:
                released = release_transaction_claim(
                    session, transaction_id, claim.claim_token, str(exc)
                )
            except Exception:
                logger.exception(
                    "could not release failed transaction claim",
                    extra={
                        "event": "transaction.claim_release_failed",
                        "transaction_id": transaction_id,
                    },
                )
        logger.exception(
            "transaction processing failed; scheduling retry",
            extra={"event": "transaction.processing_failed", "transaction_id": transaction_id},
        )
        countdown = (
            min(60, 5 * (self.request.retries + 1))
            if released
            else settings.processing_lease_seconds + 1
        )
        raise self.retry(exc=exc, countdown=countdown) from exc
    finally:
        session.close()
