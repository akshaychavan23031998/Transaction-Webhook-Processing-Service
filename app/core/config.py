from functools import lru_cache

from pydantic import Field
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
    redis_url: str = "redis://localhost:6379/0"
    transaction_processing_delay_seconds: float = Field(default=30, ge=0)
    processing_lease_seconds: int = Field(default=90, ge=1)
    outbox_dispatch_interval_seconds: float = Field(default=2, ge=0.1)
    outbox_batch_size: int = Field(default=100, ge=1, le=1000)
    webhook_signature_enabled: bool = False
    webhook_signature_secret: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
