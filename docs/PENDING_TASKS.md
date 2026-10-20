# Pending Tasks and Development Gap Analysis

**Review date:** 2026-10-20

This register separates implementation defects from testing improvements and from the explicitly deferred GitHub/cloud deliverables. No commits, pushes, deployments, resource creation, or database resets were performed.

## Current status

- P0 open: **0**
- P1 open: **0**
- P2 open: **1**
- P3 open/deferred: **3**
- Runtime database state after final verification: 175 PROCESSED transactions, 175 DISPATCHED outbox events, zero orphan events, zero expired/stuck rows.

## Initially identified findings

| Priority | Finding | Affected area | Work completed | Status |
| --- | --- | --- | --- | --- |
| P1 | Parent transaction and child outbox ordering could violate the PostgreSQL FK during flush. | `app/repositories/transaction_repository.py` | Flush the transaction parent before inserting/flushing the outbox event. | RESOLVED; live 202 and E2E evidence |
| P1 | Celery task registration was not reliable in the worker image. | `app/workers/celery_app.py` | Explicit task module inclusion. | RESOLVED; worker listed and executed the task |
| P1 | A dead worker could leave a PROCESSING row with a DISPATCHED event indefinitely. | Repository and dispatcher | Added expired transaction lease recovery and republish path. | RESOLVED; unit and live worker-crash evidence |
| P1 | Decimal-scale validation could produce HTTP 500 instead of 422. | `app/main.py` | Sanitize exception values in validation details. | RESOLVED; regression test and live request |
| P2 | Dispatcher and worker logs were not using the application JSON formatter. | `app/workers/celery_app.py`, `app/workers/dispatcher.py` | Installed the formatter through Celery setup logging and dispatcher startup. | RESOLVED; live JSON logs |
| P2 | Benchmark aggregate throughput used maximum latency as its denominator. | `scripts/benchmark_webhooks.py` | Measure total batch wall time and correct percentile rank. | RESOLVED; corrected 20/50 benchmark rerun |
| P2 | Fast tests did not provide a repeatable PostgreSQL/Redis/Celery failure harness. | `tests/`, Compose test workflow | Added/retained unit tests and live scripts, but not a full automated Compose test runner. | PENDING; see below |
| P3 | HMAC behavior is generic because no provider-specific signature contract was supplied. | `app/api/v1/webhooks.py` | Raw-body HMAC and constant-time comparison exist behind configuration. | PENDING contract; not blocking the generic assessment |
| P3 | GitHub-hosted CI execution was not run from this local audit. | `.github/workflows/ci.yml` | Workflow exists and its commands were inspected; local equivalents passed. | DEFERRED external execution |
| P3 | Cloud deployment and public submission were not performed. | `docs/deployment.md`, README | Deployment preparation remains documented. | DEFERRED by explicit scope |

## Open P2 task: automate live integration and failure recovery

**Impact:** The runtime behavior was directly verified, but a future regression would currently require manual Docker commands or the supplied scripts to reproduce all Redis, PostgreSQL, worker, dispatcher, and lease-recovery cases. The fast suite reports 14 passed and 68% application coverage, but worker/dispatcher modules are not exercised by that isolated suite.

**Affected files:** `tests/`, `docker-compose.yml`, `scripts/`.

**Exact completion steps:**

1. Add a dedicated Compose integration test profile or Testcontainers fixture with isolated PostgreSQL and Redis names/volumes.
2. Mark tests with the existing `integration` and `e2e` markers.
3. Add fixtures that wait for `/ready`, run `alembic upgrade head`, and generate unique transaction IDs.
4. Automate the already demonstrated cases: Redis stop/restart, worker SIGKILL/restart, API restart, PostgreSQL stop/restart, dispatcher stop/restart, duplicate task publish, expired lease republish, and stale token finalization.
5. Assert both HTTP outcomes and direct database invariants after every recovery case.
6. Run the profile in CI only with isolated service containers and no production credentials.

**Current evidence:** The manual/live drills in [`VERIFICATION_REPORT.md`](VERIFICATION_REPORT.md) passed, including the 90-second worker lease recovery path. This task remains open only because the evidence is not yet encoded as a single automated test command.

## Open P3 task: provider-specific HMAC adapter

No provider was named, so the implementation cannot safely guess whether the signature is hex/base64, prefixed, timestamped, or based on a provider-specific canonical string. When a provider contract is available:

1. Add the exact header and canonicalization rules to the request adapter.
2. Add valid, invalid, missing, replay-window, and malformed signature tests.
3. Enable `WEBHOOK_SIGNATURE_ENABLED` only with the provider secret in the runtime secret store.
4. Verify that malformed signed requests return the provider-approved error contract.

This is not a defect in the generic assessment path while signature verification is disabled and no provider contract exists.

## Deferred external deliverables

These are not development blockers under the requested scope:

- Run the GitHub Actions workflow in the user-owned GitHub context.
- Publish the repository and any requested assessment submission.
- Deploy API, worker, dispatcher, PostgreSQL, and Redis to a cloud platform.
- Verify a public HTTPS URL and cloud-side health/background processing.

These require user-owned credentials and external authorization, so they were intentionally not attempted.

## Completed work and verification commands

Completed during this audit or the implementation verification sequence:

- Added/updated the JSON-safe validation regression in `tests/integration/test_api.py`.
- Retained and verified lease-recovery coverage in `tests/unit/test_worker_claims.py`.
- Updated the benchmark measurement implementation.
- Rebuilt the API, worker, dispatcher, and migration images.
- Ran `ruff format --check .`, `ruff check .`, `pytest --cov=app`, `compileall`, `docker compose config --quiet`, and `alembic check`.
- Ran the live E2E, invalid-input matrix, duplicate/concurrency tests, database queries, and all six local failure/recovery drills.
- Updated README reliability, logging, CI, and audit-artifact statements.
- Created `docs/VERIFICATION_REPORT.md`.

No issue is marked RESOLVED without direct test, database, log, or runtime evidence in the verification report.
