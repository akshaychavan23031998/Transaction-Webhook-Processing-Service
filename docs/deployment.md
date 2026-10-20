# Deployment runbook

The service needs three independently restartable long-running roles: API, Celery worker, and outbox dispatcher. It also needs managed PostgreSQL and Redis.

Use a container platform that supports separate services and environment variables. Set DATABASE_URL and REDIS_URL in the platform secret store. Run alembic upgrade head as a release/migration command before starting application processes. Deploy the API, worker, and dispatcher from the same image and commit.

Verify in this order:

1. GET / returns HEALTHY.
2. GET /ready returns READY.
3. POST /v1/webhooks/transactions returns 202.
4. The transaction is initially PROCESSING.
5. The transaction becomes PROCESSED after the configured delay.
6. Replaying the same payload returns 202 with duplicate=true.

Do not place credentials in a Docker image, repository, README, or command history. Do not call deployment complete until the public URL and background processing are verified with a real request.
