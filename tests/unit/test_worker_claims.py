from datetime import UTC, datetime, timedelta

from app.models.outbox import OutboxEvent, OutboxStatus
from app.models.transaction import Transaction
from app.repositories.transaction_repository import (
    claim_transaction,
    finalize_transaction,
    recover_expired_transactions,
    release_transaction_claim,
)
from app.schemas.transaction import TransactionWebhookRequest
from app.services.transaction_service import TransactionService


def test_worker_claim_is_idempotent_and_fenced(db_session):
    payload = TransactionWebhookRequest(
        transaction_id="txn_worker_1",
        source_account="acc_user_789",
        destination_account="acc_merchant_456",
        amount="10.00",
        currency="INR",
    )
    TransactionService().accept_webhook(db_session, payload)

    first = claim_transaction(db_session, payload.transaction_id)
    second = claim_transaction(db_session, payload.transaction_id)
    assert first is not None
    assert second is None
    assert finalize_transaction(db_session, payload.transaction_id, "stale-token") is False
    assert finalize_transaction(db_session, payload.transaction_id, first.claim_token) is True
    assert claim_transaction(db_session, payload.transaction_id) is None


def test_expired_lease_can_be_recovered(db_session):
    payload = TransactionWebhookRequest(
        transaction_id="txn_worker_2",
        source_account="acc_user_789",
        destination_account="acc_merchant_456",
        amount="10.00",
        currency="INR",
    )
    TransactionService().accept_webhook(db_session, payload)
    first = claim_transaction(db_session, payload.transaction_id)
    assert first is not None
    transaction = (
        db_session.query(Transaction).filter_by(transaction_id=payload.transaction_id).one()
    )
    transaction.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    recovered = claim_transaction(db_session, payload.transaction_id)
    assert recovered is not None
    assert recovered.claim_token != first.claim_token
    assert (
        release_transaction_claim(db_session, payload.transaction_id, recovered.claim_token, "test")
        is True
    )


def test_expired_dispatched_job_is_requeued(db_session):
    payload = TransactionWebhookRequest(
        transaction_id="txn_worker_requeue",
        source_account="acc_user_789",
        destination_account="acc_merchant_456",
        amount="10.00",
        currency="INR",
    )
    TransactionService().accept_webhook(db_session, payload)
    claim = claim_transaction(db_session, payload.transaction_id)
    assert claim is not None
    transaction = (
        db_session.query(Transaction).filter_by(transaction_id=payload.transaction_id).one()
    )
    transaction.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    event = db_session.query(OutboxEvent).filter_by(transaction_id=payload.transaction_id).one()
    event.status = OutboxStatus.DISPATCHED
    event.last_attempted_at = datetime.now(UTC) - timedelta(seconds=20)
    db_session.commit()
    assert recover_expired_transactions(db_session) == 1
    assert event.status == OutboxStatus.PENDING
