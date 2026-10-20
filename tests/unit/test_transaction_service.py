import pytest

from app.core.exceptions import ConflictingTransactionError
from app.models.outbox import OutboxEvent
from app.models.transaction import TransactionStatus
from app.schemas.transaction import TransactionWebhookRequest
from app.services.transaction_service import TransactionService


def payload(amount: str = "1500.00") -> TransactionWebhookRequest:
    return TransactionWebhookRequest(
        transaction_id="txn_service_1",
        source_account="acc_user_789",
        destination_account="acc_merchant_456",
        amount=amount,
        currency="INR",
    )


def test_acceptance_is_atomic_and_duplicate_safe(db_session):
    service = TransactionService()
    first = service.accept_webhook(db_session, payload())
    second = service.accept_webhook(db_session, payload())

    assert first.duplicate is False
    assert second.duplicate is True
    assert first.transaction.status == TransactionStatus.PROCESSING
    assert db_session.query(OutboxEvent).count() == 1


def test_conflicting_duplicate_is_explicit(db_session):
    service = TransactionService()
    service.accept_webhook(db_session, payload())
    with pytest.raises(ConflictingTransactionError):
        service.accept_webhook(db_session, payload("1501.00"))
