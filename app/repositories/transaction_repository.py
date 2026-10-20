from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.outbox import OutboxEvent, OutboxStatus
from app.models.transaction import Transaction, TransactionStatus
from app.schemas.transaction import TransactionWebhookRequest

settings = get_settings()


@dataclass(frozen=True)
class ClaimedTransaction:
    transaction_id: str
    claim_token: str
    attempt: int


@dataclass(frozen=True)
class ClaimedOutboxEvent:
    event_id: int
    transaction_id: str
    event_type: str
    payload: dict
    claim_token: str


def payload_matches(transaction: Transaction, payload: TransactionWebhookRequest) -> bool:
    return (
        transaction.source_account == payload.source_account
        and transaction.destination_account == payload.destination_account
        and transaction.amount == payload.amount
        and transaction.currency == payload.currency
    )


def get_transaction(session: Session, transaction_id: str) -> Transaction | None:
    return session.execute(
        select(Transaction).where(Transaction.transaction_id == transaction_id)
    ).scalar_one_or_none()


def insert_transaction_and_outbox(
    session: Session, payload: TransactionWebhookRequest, now: datetime
) -> Transaction:
    transaction = Transaction(
        transaction_id=payload.transaction_id,
        source_account=payload.source_account,
        destination_account=payload.destination_account,
        amount=payload.amount,
        currency=payload.currency,
        status=TransactionStatus.PROCESSING,
        created_at=now,
        updated_at=now,
        processing_attempts=0,
    )
    session.add(transaction)
    # Flush the parent first because the model intentionally keeps the
    # transaction/outbox relationship lightweight; PostgreSQL enforces the FK.
    session.flush()
    session.add(
        OutboxEvent(
            event_type="TRANSACTION_PROCESS",
            transaction_id=payload.transaction_id,
            payload={"transaction_id": payload.transaction_id},
            status=OutboxStatus.PENDING,
            created_at=now,
            attempt_count=0,
        )
    )
    session.flush()
    return transaction


def claim_transaction(session: Session, transaction_id: str) -> ClaimedTransaction | None:
    now = datetime.now(UTC)
    with session.begin():
        transaction = session.execute(
            select(Transaction)
            .where(Transaction.transaction_id == transaction_id)
            .with_for_update()
        ).scalar_one_or_none()
        if transaction is None or transaction.status == TransactionStatus.PROCESSED:
            return None
        lease_expires_at = transaction.lease_expires_at
        if lease_expires_at and lease_expires_at.tzinfo is None:
            lease_expires_at = lease_expires_at.replace(tzinfo=UTC)
        if lease_expires_at and lease_expires_at > now:
            return None

        token = str(uuid4())
        attempt = transaction.processing_attempts + 1
        transaction.claim_token = token
        transaction.lease_expires_at = now + timedelta(seconds=settings.processing_lease_seconds)
        transaction.processing_attempts = attempt
        transaction.updated_at = now
        transaction.last_error = None
        return ClaimedTransaction(transaction_id, token, attempt)


def finalize_transaction(session: Session, transaction_id: str, claim_token: str) -> bool:
    now = datetime.now(UTC)
    with session.begin():
        result = session.execute(
            update(Transaction)
            .where(
                Transaction.transaction_id == transaction_id,
                Transaction.status == TransactionStatus.PROCESSING,
                Transaction.claim_token == claim_token,
            )
            .values(
                status=TransactionStatus.PROCESSED,
                processed_at=now,
                updated_at=now,
                claim_token=None,
                lease_expires_at=None,
                last_error=None,
            )
        )
        return result.rowcount == 1


def release_transaction_claim(
    session: Session, transaction_id: str, claim_token: str, error: str
) -> bool:
    now = datetime.now(UTC)
    with session.begin():
        result = session.execute(
            update(Transaction)
            .where(
                Transaction.transaction_id == transaction_id,
                Transaction.status == TransactionStatus.PROCESSING,
                Transaction.claim_token == claim_token,
            )
            .values(
                claim_token=None,
                lease_expires_at=None,
                updated_at=now,
                last_error=error[:1000],
            )
        )
        return result.rowcount == 1


def claim_outbox_events(session: Session) -> list[ClaimedOutboxEvent]:
    now = datetime.now(UTC)
    lock_until = now + timedelta(seconds=max(10, settings.outbox_dispatch_interval_seconds * 5))
    events: list[ClaimedOutboxEvent] = []
    with session.begin():
        rows = (
            session.execute(
                select(OutboxEvent)
                .where(
                    or_(
                        OutboxEvent.status == OutboxStatus.PENDING,
                        (OutboxEvent.status == OutboxStatus.DISPATCHING)
                        & (OutboxEvent.locked_until < now),
                    )
                )
                .order_by(OutboxEvent.created_at)
                .limit(settings.outbox_batch_size)
                .with_for_update(skip_locked=True)
            )
            .scalars()
            .all()
        )
        for event in rows:
            token = str(uuid4())
            event.status = OutboxStatus.DISPATCHING
            event.claim_token = token
            event.locked_until = lock_until
            event.last_attempted_at = now
            event.attempt_count += 1
            events.append(
                ClaimedOutboxEvent(
                    event.id, event.transaction_id, event.event_type, event.payload, token
                )
            )
    return events


def mark_outbox_dispatched(session: Session, event_id: int, claim_token: str) -> bool:
    with session.begin():
        result = session.execute(
            update(OutboxEvent)
            .where(
                OutboxEvent.id == event_id,
                OutboxEvent.status == OutboxStatus.DISPATCHING,
                OutboxEvent.claim_token == claim_token,
            )
            .values(
                status=OutboxStatus.DISPATCHED,
                locked_until=None,
                claim_token=None,
                last_error=None,
            )
        )
        return result.rowcount == 1


def mark_outbox_failed(session: Session, event_id: int, claim_token: str, error: str) -> bool:
    with session.begin():
        result = session.execute(
            update(OutboxEvent)
            .where(
                OutboxEvent.id == event_id,
                OutboxEvent.status == OutboxStatus.DISPATCHING,
                OutboxEvent.claim_token == claim_token,
            )
            .values(
                status=OutboxStatus.PENDING,
                locked_until=None,
                claim_token=None,
                last_error=error[:1000],
            )
        )
        return result.rowcount == 1


def recover_expired_transactions(session: Session) -> int:
    """Make a dispatched job dispatchable after its worker lease expires."""
    now = datetime.now(UTC)
    cooldown = timedelta(seconds=max(10, settings.outbox_dispatch_interval_seconds * 5))
    recovered = 0
    with session.begin():
        transactions = (
            session.execute(
                select(Transaction)
                .where(
                    Transaction.status == TransactionStatus.PROCESSING,
                    Transaction.lease_expires_at.is_not(None),
                    Transaction.lease_expires_at < now,
                )
                .with_for_update(skip_locked=True)
            )
            .scalars()
            .all()
        )
        for transaction in transactions:
            event = session.execute(
                select(OutboxEvent).where(
                    OutboxEvent.transaction_id == transaction.transaction_id,
                    OutboxEvent.event_type == "TRANSACTION_PROCESS",
                )
            ).scalar_one_or_none()
            if event is None or event.status != OutboxStatus.DISPATCHED:
                continue
            if event.last_attempted_at and event.last_attempted_at > now - cooldown:
                continue
            event.status = OutboxStatus.PENDING
            event.claim_token = None
            event.locked_until = None
            event.last_error = "requeued after expired transaction lease"
            recovered += 1
    return recovered
