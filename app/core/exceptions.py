class ConflictingTransactionError(Exception):
    """The transaction ID exists but its immutable payload differs."""


class DurableAcceptanceError(Exception):
    """The webhook could not be durably accepted."""
