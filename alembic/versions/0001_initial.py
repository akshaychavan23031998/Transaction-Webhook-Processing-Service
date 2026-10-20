"""create transactions and transactional outbox

Revision ID: 0001_initial
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("transaction_id", sa.String(length=128), nullable=False),
        sa.Column("source_account", sa.String(length=128), nullable=False),
        sa.Column("destination_account", sa.String(length=128), nullable=False),
        sa.Column("amount", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("processing_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("claim_token", sa.String(length=36)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.UniqueConstraint("transaction_id", name="uq_transactions_transaction_id"),
    )
    op.create_index("ix_transactions_status_lease", "transactions", ["status", "lease_expires_at"])
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("transaction_id", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True)),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(length=1000)),
        sa.Column("claim_token", sa.String(length=36)),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.transaction_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("transaction_id", "event_type", name="uq_outbox_transaction_event"),
    )
    op.create_index("ix_outbox_dispatchable", "outbox_events", ["status", "locked_until", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_outbox_dispatchable", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_index("ix_transactions_status_lease", table_name="transactions")
    op.drop_table("transactions")

