import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictingTransactionError, DurableAcceptanceError
from app.models.transaction import Transaction
from app.repositories.transaction_repository import (
    get_transaction,
    insert_transaction_and_outbox,
    payload_matches,
)
from app.schemas.transaction import TransactionWebhookRequest

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AcceptanceResult:
    transaction: Transaction
    duplicate: bool


class TransactionService:
    def accept_webhook(
        self, session: Session, payload: TransactionWebhookRequest
    ) -> AcceptanceResult:
        now = datetime.now(UTC)
        # The normal FastAPI dependency provides a fresh session per request. This
        # rollback also keeps the service safe for callers that queried with the
        # same session immediately before retrying a webhook.
        if session.in_transaction():
            session.rollback()
        try:
            with session.begin():
                existing = get_transaction(session, payload.transaction_id)
                if existing:
                    if not payload_matches(existing, payload):
                        raise ConflictingTransactionError(payload.transaction_id)
                    return AcceptanceResult(existing, True)
                transaction = insert_transaction_and_outbox(session, payload, now)
                return AcceptanceResult(transaction, False)
        except ConflictingTransactionError:
            raise
        except IntegrityError:
            session.rollback()
            try:
                existing = get_transaction(session, payload.transaction_id)
            except SQLAlchemyError as exc:
                session.rollback()
                logger.exception(
                    "database lookup failed after duplicate race", extra={"event": "webhook.failed"}
                )
                raise DurableAcceptanceError from exc
            if existing and payload_matches(existing, payload):
                return AcceptanceResult(existing, True)
            if existing:
                raise ConflictingTransactionError(payload.transaction_id) from None
            raise DurableAcceptanceError from None
        except SQLAlchemyError as exc:
            session.rollback()
            logger.exception("database transaction failed", extra={"event": "webhook.failed"})
            raise DurableAcceptanceError from exc
