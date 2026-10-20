from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

ACCOUNT_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
TRANSACTION_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"


class TransactionWebhookRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_id: str = Field(min_length=1, max_length=128, pattern=TRANSACTION_ID_PATTERN)
    source_account: str = Field(min_length=1, max_length=128, pattern=ACCOUNT_PATTERN)
    destination_account: str = Field(min_length=1, max_length=128, pattern=ACCOUNT_PATTERN)
    amount: Decimal = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")

    @field_validator("amount")
    @classmethod
    def validate_scale(cls, value: Decimal) -> Decimal:
        if abs(value.as_tuple().exponent) > 4:
            raise ValueError("amount supports at most 4 decimal places")
        return value


class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    transaction_id: str
    source_account: str
    destination_account: str
    amount: Decimal
    currency: str
    status: str
    created_at: datetime
    processed_at: datetime | None

    @field_serializer("amount")
    def serialize_amount(self, value: Decimal) -> str:
        return format(value, "f")


class WebhookAcceptedResponse(BaseModel):
    transaction_id: str
    status: str
    duplicate: bool
    message: str


class HealthResponse(BaseModel):
    status: str
    current_time: str


class ReadinessResponse(BaseModel):
    status: str
    database: str
    redis: str


class ErrorResponse(BaseModel):
    error: dict
