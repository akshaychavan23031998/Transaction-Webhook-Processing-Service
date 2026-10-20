# Transaction Webhook Service Verification Report

**Verification date:** 2026-10-20

**Scope:** local development audit, API verification, database verification, background processing, concurrency, performance, and reversible failure-recovery testing. GitHub publishing, cloud deployment, and paid resources were not performed.

## Overall result

**PASS for the local implementation, with P2 test-harness limitations.** No P0 or P1 runtime blocker remains from this audit. The service accepted and durably stored webhooks, processed them through PostgreSQL -> transactional outbox -> dispatcher -> Redis -> Celery -> PostgreSQL, recovered from the requested local failure scenarios, and passed the final post-rebuild checks.

The remaining limitation is coverage organization: the fast pytest suite uses isolated SQLite and the live PostgreSQL/Redis/Celery failure drills are currently executable scripts/manual procedures rather than a fully automated Compose integration suite. This is recorded as P2 in [`PENDING_TASKS.md`](PENDING_TASKS.md), not as a claim that the automated suite covers every live failure mode.

## Environment and evidence boundary

- Host: macOS, Python 3.12.8; Docker Compose services ran on Docker Desktop Linux/aarch64.
- Application dependencies were installed from the pinned `pyproject.toml` declarations.
- Final Compose services: API, PostgreSQL 16, Redis 7, one Celery worker with concurrency 2, dispatcher, and migration service.
- `TRANSACTION_PROCESSING_DELAY_SECONDS=30` and `PROCESSING_LEASE_SECONDS=90` were used for the final stack.
- Existing Compose database and Redis volumes were preserved. No volume reset, table reset, record deletion, commit, push, remote change, deployment, or paid resource creation was performed.
- No project `CLAUDE.md`, `.claude/`, or `.mcp.json` instruction files were present, and the exact workspace path had no imported Claude project-context manifest match. The review therefore used the checked-in source, Compose configuration, tests, and runtime evidence.

`PASS` below means the behavior was directly observed in this audit. `PENDING` means the behavior is implemented or manually verified but still needs a repeatable automated harness. `DEFERRED` means it is outside the explicitly requested local scope.

## Architecture audit

The implementation has the expected boundaries:

1. FastAPI validates the webhook and calls the service layer.
2. The service writes the transaction and one outbox event in one PostgreSQL transaction.
3. The dispatcher claims pending or expired outbox leases, publishes a named Celery task to Redis, and marks the event dispatched.
4. The Celery worker claims a transaction using a lease and fencing token, performs the configured 30-second simulation, and conditionally finalizes the row.
5. The dispatcher recovery sweep re-queues a dispatched event when its transaction lease expires, covering a worker that dies after claim.
6. Database uniqueness, payload comparison, row locking, late acknowledgements, worker-loss requeue, leases, and fencing prevent unsafe duplicate state transitions.

Reviewed areas: FastAPI routes, Pydantic schemas, service/repository boundaries, SQLAlchemy models, PostgreSQL configuration, Alembic, Redis/Celery configuration, worker and dispatcher behavior, logging, environment configuration, Docker Compose, tests, scripts, README, and CI workflow.

## API verification

| Endpoint or case | Expected | Actual evidence | Result |
| --- | --- | --- | --- |
| `GET /` | 200, HEALTHY, dynamic UTC | 200; e.g. `{"status":"HEALTHY","current_time":"2026-10-20T14:02:31.972185Z"}` | PASS |
| `GET /ready` healthy | 200 and both dependencies READY | 200; `{"status":"READY","database":"READY","redis":"READY"}` | PASS |
| Fresh `POST /v1/webhooks/transactions` | 202 under 500 ms, PROCESSING | Final post-rebuild E2E returned 202 in 25.48 ms; database row and outbox were committed | PASS |
| Initial transaction query | 200, request data preserved, `processed_at=null` | Final E2E returned PROCESSING with amount `1500.0000` and null `processed_at` | PASS |
| Processed transaction query | PROCESSED and populated `processed_at` | Final E2E returned PROCESSED and a UTC `processed_at` | PASS |
| Unknown transaction query | 404 | `GET /v1/transactions/does_not_exist` returned 404 | PASS |
| Exact sequential replay | 202 with `duplicate=true` | Final E2E replay returned 202 with `status=PROCESSED`, `duplicate=true` | PASS |
| Conflicting replay, including completed row | 409 and no mutation | Returned 409; `processing_attempts` and `processed_at` were unchanged | PASS |
| Missing fields | 422 | 422 | PASS |
| Empty transaction ID | 422 | 422 | PASS |
| Invalid account identifiers | 422 | 422 for spaces and empty account values | PASS |
| Negative or zero amount | 422 | 422 | PASS |
| Invalid currency | 422 | 422 for lowercase and wrong length | PASS |
| Wrong data types | 422 | 422 | PASS |
| Malformed JSON | 422 | 422 | PASS |
| Excessively long input | 422 | 422 for a 129-character transaction ID | PASS |
| More than four decimal places | 422, JSON response | Initially reproduced as 500; fixed and then verified as 422 with JSON-safe error details | PASS |
| Unknown fields | 422 | 422 because the schema forbids extras | PASS |
| Repeated GET | No mutation | Two identical GET responses; processing metadata unchanged | PASS |

The live invalid-input matrix covered every requested category. The precision case exposed and fixed the only API correctness defect found during this audit.

## Real 30-second background processing

Final post-rebuild transaction: `txn_audit_post_rebuild_e2e_20261020`.

| Event | UTC timestamp |
| --- | --- |
| Transaction created | `2026-10-20T14:01:43.548849Z` |
| Dispatcher publish attempt | `2026-10-20T14:01:43.663323Z` |
| Outbox marked DISPATCHED | `2026-10-20T14:01:43.719312Z` |
| Worker claim/start | `2026-10-20T14:01:43.742065Z` |
| Worker completion log | `2026-10-20T14:02:13.754522Z` |
| Database `processed_at` | `2026-10-20T14:02:13.745315Z` |

Measured results:

- API acknowledgement: 25.48 ms, immediate `PROCESSING` response.
- Outbox/queue wait from creation to worker start: about 193 ms.
- Actual worker simulation: about 30.012 seconds.
- Creation to database completion: about 30.196 seconds.
- Final replay: 202 with `duplicate=true`.

This demonstrates the required FastAPI -> PostgreSQL -> outbox -> dispatcher -> Redis -> Celery -> PostgreSQL path. The database query after completion showed `PROCESSED`, populated `processed_at`, and one processing attempt.

## Idempotency, concurrency, and fencing

- Sequential duplicate: 202 with `duplicate=true`.
- Twenty simultaneous identical requests: all 20 returned 202; exactly one new acceptance and 19 identical duplicates (`elapsed_ms=58.52`).
- Fifty simultaneous unique requests: all 50 returned 202. The benchmark workload was later drained completely.
- Duplicate Celery delivery while the original task held its lease: two duplicate tasks logged `processing_skipped`; the original transaction ended with `processing_attempts=1` and one `processed_at`.
- Completed transaction replay with a changed amount: 409; metadata remained unchanged.
- Live fencing test: first claim attempt 1, forced expired test lease, second claim attempt 2, stale token finalization `False`, current token finalization `True`.
- Worker-crash test: the dispatched transaction was reclaimed after lease expiry and finalized by attempt 2; the stale worker could not finalize the newer claim.

The results demonstrate at-least-once delivery with effectively-once durable state transitions for this simulated operation. They do not claim exactly-once execution for arbitrary external side effects.

## Performance results

The benchmark measures webhook acknowledgement latency, not 30-second completion time. The corrected script uses total batch wall time for aggregate throughput and a nearest-rank percentile calculation.

| Workload | Requests | Success/failure | Average | p50 | p95 | p99 | Max | Batch time | Aggregate accepted/s |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Normal 20-request batch | 20 | 20 / 0 | 78.16 ms | 79.04 ms | 86.54 ms | 88.31 ms | 88.31 ms | 103.68 ms | 192.90 |
| 50-request batch submitted while worker load was active | 50 | 50 / 0 | 97.45 ms | 98.07 ms | 116.88 ms | 118.31 ms | 118.31 ms | 132.08 ms | 378.57 |
| Concurrent identical delivery | 20 | 20 / 0 | See elapsed | N/A | N/A | N/A | N/A | 58.52 ms total | one new, 19 duplicates |

All observed acknowledgement latencies were below the 500 ms local target. These are local Docker Desktop observations, not a capacity guarantee for production hardware, network conditions, or larger payloads.

## Reliability and crash recovery

| Scenario | Actual result | Result |
| --- | --- | --- |
| Redis stopped | Readiness returned 503 with database READY and Redis NOT_READY. A webhook still returned 202 and was persisted with outbox PENDING. After Redis restart it processed to PROCESSED. | PASS |
| Celery worker SIGKILL during processing | Transaction was claimed at attempt 1, worker was killed, worker restarted, dispatcher logged `transaction.recovery_requeued` after the 90-second lease, and the transaction completed at attempt 2. | PASS |
| FastAPI restart after acceptance | Accepted row was queryable as PROCESSING after API restart and later became PROCESSED. | PASS |
| PostgreSQL stopped | Readiness returned 503 with database NOT_READY. Webhook returned 503 `durable_acceptance_unavailable`; after recovery the transaction lookup was 404, proving no false durable acknowledgement. | PASS |
| Dispatcher stopped before publish | Webhook returned 202 and the outbox remained PENDING. After dispatcher restart it was dispatched and the transaction became PROCESSED. | PASS |
| Expired lease with DISPATCHED outbox | Live worker-crash case showed the event requeued and republished; final outbox status was DISPATCHED and the transaction was PROCESSED. | PASS |

All services were restored after each drill. No volume or database reset was used.

## Database and migration verification

Final database state after the final E2E:

- Transactions: 175 `PROCESSED`, 0 `PROCESSING`.
- Outbox events: 175 `DISPATCHED`, 0 pending or dispatching.
- Orphan outbox events: 0.
- Expired processing rows: 0.
- Expired dispatching rows: 0.
- Alembic current/head: `0001_initial (head)`.
- `alembic check`: `No new upgrade operations detected.`

Verified schema constraints and indexes:

- Unique transaction ID: `uq_transactions_transaction_id`.
- Foreign key from `outbox_events.transaction_id` to `transactions.transaction_id` with cascade delete.
- Unique `(transaction_id, event_type)` outbox constraint.
- `ix_transactions_status_lease` for recovery scans.
- `ix_outbox_dispatchable` for dispatcher scans.
- PostgreSQL primary keys on both tables.

Amounts were stored as `NUMERIC(20,4)` and returned as strings. The final E2E preserved `1500.0000` and `INR` exactly.

## Automated checks

| Check | Actual result |
| --- | --- |
| Pytest | 14 passed, 0 failed, 0 skipped |
| Coverage | 68% of 518 application statements in the isolated fast suite |
| Ruff check | Passed |
| Ruff format check | Passed; 35 files already formatted |
| Python compileall | Passed |
| Docker Compose config | Passed |
| Alembic migration check | Passed; no new operations |
| Final Docker health | API, PostgreSQL, and Redis healthy; worker and dispatcher running |

There was one Starlette `BlockingPortal` deprecation warning from the installed test dependency stack. It did not fail the suite. Worker/dispatcher runtime behavior was verified with the live Compose and failure drills; those drills are not all represented as pytest cases yet.

## Bugs found and fixed

| Priority | Problem | Change | Verification |
| --- | --- | --- | --- |
| P1 | PostgreSQL could reject the outbox insert because the child was flushed before the parent transaction row under the FK. | Flush the transaction parent before adding the outbox event. | Live webhook returned 202 and database/outbox rows were created; E2E completed. |
| P1 | Celery worker initially had an empty task registry. | Explicitly include `app.workers.tasks` in the Celery app. | Worker listed `app.workers.tasks.process_transaction`; live processing completed. |
| P1 | A worker death could leave `PROCESSING` plus `DISPATCHED` permanently stuck after the lease expired. | Added `recover_expired_transactions()` and dispatcher recovery/republication. | Unit test, live SIGKILL drill, dispatcher `transaction.recovery_requeued` log, final PROCESSED row. |
| P1 | Pydantic amount-scale errors returned HTTP 500 because a `ValueError` object was not JSON serializable. | Added recursive JSON-safe validation-detail conversion. | Regression test, live precision request returned 422. |
| P2 | Worker and dispatcher logs ignored the project JSON formatter. | Added Celery `setup_logging` hook and dispatcher formatter setup. | Live worker/dispatcher logs now contain JSON event, logger, transaction ID, and timestamp fields. |
| P2 | Benchmark throughput divided by maximum request latency rather than total batch duration. | Measure batch wall time and use it for aggregate throughput; corrected percentile rank. | Corrected 20/50 benchmarks recorded above. |
| P2 | Early service tests could leave an active SQLAlchemy transaction and SQLite timezone behavior differed from PostgreSQL. | Adjusted service session handling and test timestamp normalization. | Fast suite passed after the fixes. |

## Code quality and security review

- SQLAlchemy expressions and parameterized ORM queries are used; no SQL injection path was found.
- Monetary values use Decimal/Pydantic and PostgreSQL NUMERIC; no cents conversion or binary float path was found.
- API request work does not wait for the simulated 30-second worker delay.
- Sessions are closed through dependencies, worker `finally`, and dispatcher `finally` blocks.
- Redis readiness clients are now closed with a context manager.
- Transactional acceptance and outbox insertion are atomic.
- Late acknowledgements, worker-loss rejection, leases, and fencing are configured.
- Secrets are environment-based; no real secrets were written to source or reports.
- Optional HMAC uses the raw request body and constant-time comparison. A provider-specific signature contract was not supplied, so provider adapter semantics remain a documented limitation.
- Docker services have PostgreSQL and Redis health checks; API has an HTTP health check.
- The application runs as non-root in the image.

## README verification

README coverage was updated and checked against source/runtime evidence. It documents the architecture, Mermaid flows, API contracts, exact decimal behavior, outbox and recovery decisions, Docker setup, testing commands, benchmark commands, environment names, CI workflow, limitations, and the two audit documents. It now distinguishes executed local failure drills from unexecuted GitHub-hosted/cloud work.

## Final assessment checklist

| Assessment requirement | Status |
| --- | --- |
| FastAPI routes and validation | PASS |
| 202 durable webhook acceptance | PASS |
| PostgreSQL persistence and migration | PASS |
| Redis/Celery background processing | PASS |
| Real 30-second processing | PASS |
| Transactional outbox | PASS |
| Idempotency and conflicting replay | PASS |
| Concurrent duplicates and duplicate tasks | PASS |
| Worker leases and stale fencing | PASS |
| Dispatcher/worker/API/dependency recovery | PASS locally |
| Database constraints and no stuck rows | PASS |
| 500 ms acknowledgement target | PASS under measured local workloads |
| Ruff, pytest, compile, Compose, Alembic checks | PASS |
| Automated live failure-injection suite | PENDING P2 |
| Provider-specific HMAC contract | PENDING until provider contract exists |
| GitHub publishing and cloud deployment | DEFERRED by scope, not a development defect |

## Final conclusion

The local transaction webhook service is working and assessment-ready for the implemented requirements. No P0/P1 development blocker was observed after final re-verification. The remaining P2 item is to convert the already demonstrated live failure drills into repeatable automated Compose integration tests; cloud and GitHub submission work remains explicitly deferred.
