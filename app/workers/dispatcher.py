import logging
import signal
from threading import Event

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.repositories.transaction_repository import (
    claim_outbox_events,
    mark_outbox_dispatched,
    mark_outbox_failed,
    recover_expired_transactions,
)
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def dispatch_once() -> int:
    session = SessionLocal()
    try:
        recovered = recover_expired_transactions(session)
        events = claim_outbox_events(session)
    finally:
        session.close()

    if recovered:
        logger.warning(
            "requeued transactions with expired worker leases",
            extra={"event": "transaction.recovery_requeued", "attempt": recovered},
        )

    dispatched = 0
    for event in events:
        session = SessionLocal()
        try:
            logger.info(
                "publishing outbox event",
                extra={
                    "event": "outbox.dispatch_attempted",
                    "transaction_id": event.transaction_id,
                },
            )
            celery_app.send_task(
                "app.workers.tasks.process_transaction",
                args=[event.transaction_id],
            )
            if mark_outbox_dispatched(session, event.event_id, event.claim_token):
                dispatched += 1
                logger.info(
                    "outbox event dispatched",
                    extra={"event": "outbox.dispatched", "transaction_id": event.transaction_id},
                )
        except Exception as exc:
            logger.exception(
                "outbox publish failed; event will be retried",
                extra={"event": "outbox.dispatch_failed", "transaction_id": event.transaction_id},
            )
            try:
                mark_outbox_failed(session, event.event_id, event.claim_token, str(exc))
            except Exception:
                logger.exception(
                    "could not reset failed outbox claim", extra={"event": "outbox.recovery_failed"}
                )
        finally:
            session.close()
    return dispatched


def run_dispatcher() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    stop_event = Event()

    def request_stop(signum, _frame) -> None:
        logger.info(
            "dispatcher shutdown requested",
            extra={"event": "outbox.dispatcher_shutdown_requested", "signal": signum},
        )
        stop_event.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    logger.info("outbox dispatcher started", extra={"event": "outbox.dispatcher_started"})
    while not stop_event.is_set():
        try:
            dispatch_once()
        except Exception:
            logger.exception("dispatcher loop failed", extra={"event": "outbox.dispatcher_failed"})
        stop_event.wait(settings.outbox_dispatch_interval_seconds)
    logger.info("outbox dispatcher stopped", extra={"event": "outbox.dispatcher_stopped"})


if __name__ == "__main__":
    run_dispatcher()
