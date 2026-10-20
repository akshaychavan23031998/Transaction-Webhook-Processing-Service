import json
from pathlib import Path

from app.core.config import Settings
from app.workers import tasks


def test_standard_postgres_urls_use_the_installed_psycopg_driver():
    postgresql = Settings(database_url="postgresql://user:password@db.example/transactions")
    postgres = Settings(database_url="postgres://user:password@db.example/transactions")

    assert postgresql.database_url == ("postgresql+psycopg://user:password@db.example/transactions")
    assert postgres.database_url == "postgresql+psycopg://user:password@db.example/transactions"


def test_vercel_daemons_use_the_shared_root_build_context():
    project_root = Path(__file__).parents[2]
    config = json.loads((project_root / "vercel.json").read_text())
    daemons = config["daemons"]

    assert set(daemons) == {"celery-worker", "outbox-dispatcher"}
    for daemon in daemons.values():
        assert daemon["root"] == "."
        assert daemon["entrypoint"] == "Dockerfile"
        assert daemon["instances"] == {"iad1": 1}
        assert daemon["resources"]["requests"]["memory"] == "1Gi"
        assert daemon["terminationGracePeriodSeconds"] == 60

    assert daemons["celery-worker"]["command"][:3] == [
        "celery",
        "-A",
        "app.workers.celery_app:celery_app",
    ]
    assert daemons["outbox-dispatcher"]["command"] == [
        "python",
        "-m",
        "app.workers.dispatcher",
    ]


def test_celery_task_is_registered_from_the_shared_application_package():
    assert tasks.process_transaction.name == "app.workers.tasks.process_transaction"
