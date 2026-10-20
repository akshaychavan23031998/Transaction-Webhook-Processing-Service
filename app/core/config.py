from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "transaction-webhook-service"
    app_env: str = "local"
    log_level: str = "INFO"
    database_url: str = (
        "postgresql+psycopg://transaction_user:transaction_password@localhost:5432/transactions"
    )
    database_pool_size: int = Field(default=10, ge=1)
    database_max_overflow: int = Field(default=10, ge=0)
    database_pool_timeout_seconds: int = Field(default=30, ge=1)
    database_pool_recycle_seconds: int = Field(default=1800, ge=0)
    redis_url: str = "redis://localhost:6379/0"
    transaction_processing_delay_seconds: float = Field(default=30, ge=0)
    processing_lease_seconds: int = Field(default=90, ge=1)
    outbox_dispatch_interval_seconds: float = Field(default=2, ge=0.1)
    outbox_batch_size: int = Field(default=100, ge=1, le=1000)
    webhook_signature_enabled: bool = False
    webhook_signature_secret: str | None = None

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        """Make provider connection strings compatible with the installed psycopg driver."""
        if not isinstance(value, str):
            return value
        if value.startswith("postgres://"):
            return "postgresql+psycopg://" + value.removeprefix("postgres://")
        if value.startswith("postgresql://"):
            return "postgresql+psycopg://" + value.removeprefix("postgresql://")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
