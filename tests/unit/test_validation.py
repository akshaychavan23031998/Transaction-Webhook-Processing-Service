from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.transaction import TransactionWebhookRequest


def valid_payload() -> dict:
    return {
        "transaction_id": "txn_123",
        "source_account": "acc_user_789",
        "destination_account": "acc_merchant_456",
        "amount": "1500.1250",
        "currency": "INR",
    }


def test_decimal_amount_is_exact():
    payload = TransactionWebhookRequest.model_validate(valid_payload())
    assert payload.amount == Decimal("1500.1250")


@pytest.mark.parametrize(
    "field,value",
    [
        ("amount", "0"),
        ("currency", "usd"),
        ("transaction_id", "bad id"),
    ],
)
def test_invalid_values_are_rejected(field: str, value: str):
    payload = valid_payload()
    payload[field] = value
    with pytest.raises(ValidationError):
        TransactionWebhookRequest.model_validate(payload)


def test_unknown_fields_are_rejected():
    payload = valid_payload()
    payload["unexpected"] = True
    with pytest.raises(ValidationError):
        TransactionWebhookRequest.model_validate(payload)
