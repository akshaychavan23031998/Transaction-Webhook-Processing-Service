# Vercel Hobby Deployment Guide

This guide prepares the transaction webhook service for a Vercel Hobby deployment using:

- Vercel FastAPI Functions for the HTTP API.
- One Vercel Daemon for the Celery worker.
- One Vercel Daemon for the transactional-outbox dispatcher.
- External PostgreSQL.
- External Redis-compatible TCP/TLS connectivity.

## Deployment status

The repository is **Vercel-compatible and deployment-ready for manual setup**, but no Vercel project, hosted database, hosted Redis database, or cloud deployment was created or verified by this change.

The local Compose architecture remains the source of truth:

~~~text
HTTP Function -> PostgreSQL transaction + outbox
                         |
                         v
                 dispatcher daemon -> Redis -> Celery worker
                         ^                         |
                         +---- recovery sweep <----+
~~~

The transactional outbox remains the durable source of processing intent. Redis is a transport, not the system of record.

## Official references checked

The configuration follows the official documentation checked on 2026-10-20:

- [Vercel FastAPI](https://vercel.com/docs/frameworks/backend/fastapi)
- [Vercel Python runtime](https://vercel.com/docs/functions/runtimes/python)
- [Vercel Daemons](https://vercel.com/docs/daemons)
- [Daemon configuration reference](https://vercel.com/docs/daemons/config-reference)
- [Daemon limits](https://vercel.com/docs/daemons/limits)
- [Vercel Hobby plan](https://vercel.com/docs/plans/hobby)
- [Neon serverless connection pooling](https://neon.com/docs/guides/serverless-connection-pooling)
- [Neon Free plan information](https://neon.com/blog/neon-free-plan-1-gb-per-project)
- [Upstash Celery integration](https://upstash.com/docs/redis/integrations/celery)
- [Upstash Redis pricing](https://upstash.com/pricing/redis)

Vercel Daemons are currently documented as beta. Recheck the official references before deployment because plan limits and beta capabilities can change.

## Compatibility decision

| Area | Decision | Status |
|---|---|---|
| FastAPI entrypoint | Existing app instance in app/main.py; explicit app.main:app in pyproject.toml | Implemented |
| Public routes | Keep all existing routes unchanged | Preserved |
| Daemon build context | Repository root and existing Dockerfile for both daemons | Implemented |
| Celery worker | Reuse app.workers.celery_app:celery_app and registered tasks | Preserved |
| Dispatcher | Reuse python -m app.workers.dispatcher | Preserved |
| Worker count | One instance, Celery concurrency 1 | Configured |
| Dispatcher count | One instance | Configured |
| Shutdown | 60-second grace period and dispatcher signal handling | Implemented |
| PostgreSQL URLs | Normalize standard URLs to the installed psycopg driver | Implemented |
| Serverless DB pooling | Pool size, overflow, timeout, and recycle are configurable | Implemented |
| Redis | Existing REDIS_URL remains broker and result backend | Preserved |
| Migration | Run Alembic manually with a trusted direct database URL | Manual step |
| Production deployment | Not executed | Pending |

## Why the Daemon root is the repository root

A Vercel Daemon Docker build context is its configured root. The existing Dockerfile copies app, alembic, and scripts from that context. A worker-only root would break shared imports or require a second application tree.

Both Daemons therefore use:

~~~json
{
  "root": ".",
  "entrypoint": "Dockerfile"
}
~~~

The command is overridden per Daemon:

- Celery worker: celery -A app.workers.celery_app:celery_app worker --loglevel=INFO --concurrency=1
- Dispatcher: python -m app.workers.dispatcher

This keeps Vercel and Docker Compose on the same application image.

## Vercel configuration

The checked-in vercel.json declares two production Daemons:

~~~json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "daemons": {
    "celery-worker": {
      "root": ".",
      "entrypoint": "Dockerfile",
      "command": [
        "celery",
        "-A",
        "app.workers.celery_app:celery_app",
        "worker",
        "--loglevel=INFO",
        "--concurrency=1"
      ],
      "instances": {
        "iad1": 1
      },
      "resources": {
        "requests": {
          "memory": "1Gi"
        }
      },
      "terminationGracePeriodSeconds": 60
    },
    "outbox-dispatcher": {
      "root": ".",
      "entrypoint": "Dockerfile",
      "command": [
        "python",
        "-m",
        "app.workers.dispatcher"
      ],
      "instances": {
        "iad1": 1
      },
      "resources": {
        "requests": {
          "memory": "1Gi"
        }
      },
      "terminationGracePeriodSeconds": 60
    }
  }
}
~~~

Daemon objects use only the documented fields: root, entrypoint, command, instances, resources, and terminationGracePeriodSeconds. Do not add Docker Compose fields inside a Daemon object.

The FastAPI Function is discovered from app/main.py. No duplicate root app.py was added. The explicit pyproject.toml setting is:

~~~toml
[tool.vercel]
entrypoint = "app.main:app"
~~~

Vercel currently lists Python 3.12 as the default supported Python version, matching this project's requires-python declaration.

## Vercel Hobby constraints

The current Daemon documentation records:

- Daemons run with production deployments; preview deployments do not run them.
- Hobby has a team-wide quota of 10 Active CPU-hours per month for Daemons.
- Waiting for an empty queue does not count as Active CPU, but TLS/network work and actual task execution do.
- Hobby Daemon instances support 1 GiB or 2 GiB and one vCPU.
- Daemons use Linux amd64 images.
- The default shutdown grace period is 30 seconds; this project requests 60 seconds.
- Vercel restarts Daemons after exit or crash, but a deployment rollout can interrupt a worker.
- Autoscaling and inbound Daemon traffic are not available during the documented beta.

The two configured 1 GiB Daemons and one Celery worker process are conservative. The 10-hour quota can be exhausted by long-running or high-activity workloads, at which point Vercel can stop the team's Daemons until the next month or an upgrade. Hobby is suitable for an assessment or low-volume demonstration, not a production reliability guarantee.

The worker's 90-second database lease is longer than its 30-second simulated operation. If a rollout interrupts the worker, the existing dispatcher recovery sweep can requeue the dispatched event after lease expiry.

## External PostgreSQL

The local postgres service in docker-compose.yml is not a Vercel production database. Use a managed PostgreSQL provider.

Neon is a practical candidate for a small assessment deployment. The current Neon information checked for this guide lists a free project allowance of 1 GB storage and 100 CU-hours per project per month. Neon can scale compute to zero, so the first request after inactivity can have startup latency.

### Neon connection strategy

Use two connection strings:

1. Pooled application URL: use the Neon URL whose host contains -pooler for the Vercel Function and both Daemons.
2. Direct migration URL: use the non-pooler URL for Alembic and administrative work.

Copy generated Neon URLs exactly from the Neon Console. Do not put a real password in this repository or this guide.

The application normalizes standard postgresql:// and postgres:// URLs to postgresql+psycopg:// because psycopg is the installed SQLAlchemy driver.

Recommended Vercel database settings:

~~~text
DATABASE_POOL_SIZE=1
DATABASE_MAX_OVERFLOW=0
DATABASE_POOL_TIMEOUT_SECONDS=10
DATABASE_POOL_RECYCLE_SECONDS=300
~~~

A small pool is important because Vercel can create multiple Function instances and each instance can otherwise open a larger SQLAlchemy pool. Neon pooling reduces pressure on the underlying database, but it does not remove the need to control client-side pool sizes.

## External Redis

Celery requires Redis protocol access. An HTTP Redis REST URL is not a replacement for a Celery broker URL.

Upstash documents Celery support using a TLS TCP connection:

~~~text
REDIS_URL=rediss://:TOKEN@HOST:PORT?ssl_cert_reqs=required
~~~

Use the endpoint, port, and token from the provider console. Do not copy the token into Git, README files, screenshots, or shell history.

The existing application uses REDIS_URL for:

- Celery broker.
- Celery result backend.
- FastAPI readiness PING.

The current Upstash pricing page lists a free database allowance of 256 MB, 10 GB monthly bandwidth, and 500K monthly commands. Upstash's Celery documentation warns that polling can increase command usage. A continuously running dispatcher and worker can therefore exhaust a free Redis allowance faster than an HTTP-only application. Monitor usage before using this beyond an assessment demonstration.

The transactional outbox protects accepted work if Redis is temporarily unavailable. It does not make Redis unlimited or replace Redis availability for timely processing.

## Environment variables

Add these as Production environment variables in the Vercel project. Set Preview variables only if you intentionally want to test the API without production Daemons.

| Variable | Value or guidance | Required |
|---|---|---|
| APP_NAME | transaction-webhook-service | No |
| APP_ENV | production | Recommended |
| LOG_LEVEL | INFO | No |
| DATABASE_URL | Neon pooled PostgreSQL URL with TLS parameters | Yes |
| DATABASE_POOL_SIZE | 1 | Recommended on Vercel |
| DATABASE_MAX_OVERFLOW | 0 | Recommended on Vercel |
| DATABASE_POOL_TIMEOUT_SECONDS | 10 | Recommended on Vercel |
| DATABASE_POOL_RECYCLE_SECONDS | 300 | Recommended on Vercel |
| REDIS_URL | TLS TCP URL beginning with rediss:// | Yes |
| TRANSACTION_PROCESSING_DELAY_SECONDS | 30 | Yes for assessment behavior |
| PROCESSING_LEASE_SECONDS | 90 | Yes for recovery margin |
| OUTBOX_DISPATCH_INTERVAL_SECONDS | 2 | No |
| OUTBOX_BATCH_SIZE | 100 | No |
| WEBHOOK_SIGNATURE_ENABLED | false until provider contract exists | No |
| WEBHOOK_SIGNATURE_SECRET | Provider secret only when HMAC is enabled | Conditional |

The worker and dispatcher receive the same database and Redis variables because the Daemon configuration runs the same application image.

Do not add DATABASE_URL, REDIS_URL, or provider secrets to vercel.json. Do not commit a .env file.

## Step-by-step Vercel project setup

### 1. Import the repository

In Vercel:

1. Choose New Project.
2. Import the personal repository:
   https://github.com/akshaychavan23031998/Transaction-Webhook-Processing-Service
3. Keep the production branch as main.
4. Keep the Root Directory as ./.
5. Select the FastAPI preset if Vercel asks for a framework preset.
6. Do not add custom rewrites.
7. Do not add a second API entrypoint.

The repository root contains pyproject.toml, app/main.py, Dockerfile, and vercel.json.

### 2. Create external services

Create or connect PostgreSQL and Redis in their provider dashboards. This guide does not create resources.

For Neon:

1. Create a project and database branch.
2. Copy the pooled application URL for DATABASE_URL.
3. Keep the direct URL separately for migrations.
4. Confirm the database is reachable with TLS.

For Upstash:

1. Create a Redis database with TCP/TLS access.
2. Copy host, port, and token.
3. Form the rediss:// URL with ssl_cert_reqs=required.
4. Do not use REST URL or REST token variables for Celery.

### 3. Add Production environment variables

Open Project Settings → Environment Variables and enter the names from the table above. Paste only the value into each Vercel field.

Avoid putting a direct migration URL in the project unless there is a specific operational need. Run migrations from a trusted local shell instead.

### 4. Run the initial migration

The migration is not run during a Function request or Daemon image build.

From the project root, after activating the local environment, set the direct URL only for the command session:

~~~bash
export DATABASE_URL='PASTE_THE_DIRECT_POSTGRES_URL_HERE'
export DATABASE_POOL_SIZE=1
export DATABASE_MAX_OVERFLOW=0
export DATABASE_POOL_TIMEOUT_SECONDS=30
export DATABASE_POOL_RECYCLE_SECONDS=300
.venv/bin/alembic upgrade head
.venv/bin/alembic current
.venv/bin/alembic check
unset DATABASE_URL
~~~

Replace the placeholder locally and do not paste the real value into a ticket, commit, or chat. Confirm the migration target is 0001_initial (head). Do not run this against a shared or production database without reviewing the target URL and obtaining approval.

### 5. Deploy the API

Start the deployment from the Vercel dashboard after environment variables and migration are ready. The deployment should build the FastAPI Function and the two Daemon images.

The Daemons are production resources. A preview deployment can validate project code but will not run the worker and dispatcher continuously.

### 6. Observe the rollout

Inspect:

- Function build logs.
- Daemon build logs.
- Production Function logs.
- celery-worker logs.
- outbox-dispatcher logs.
- Daemon restart events.
- Active CPU usage and monthly quota.

The worker should log Celery startup and task registration. The dispatcher should log outbox.dispatcher_started. Do not claim successful background processing until a real transaction reaches PROCESSED.

## Public verification procedure

Set the deployed URL locally without committing it:

~~~bash
export BASE_URL='https://YOUR_PROJECT.vercel.app'
curl -i "$BASE_URL/"
curl -i "$BASE_URL/ready"
curl -i "$BASE_URL/docs"
~~~

Expected health is 200 with HEALTHY and a generated UTC timestamp. Readiness must be 200 with database READY and redis READY. If either dependency is unavailable, readiness should be 503.

Submit a fresh transaction:

~~~bash
export TXN_ID="txn_vercel_$(date +%s)"
curl -i -X POST "$BASE_URL/v1/webhooks/transactions" \
  -H 'Content-Type: application/json' \
  -d "{
    \"transaction_id\": \"$TXN_ID\",
    \"source_account\": \"acc_user_789\",
    \"destination_account\": \"acc_merchant_456\",
    \"amount\": \"1500.00\",
    \"currency\": \"INR\"
  }"
~~~

Immediately query it:

~~~bash
curl -sS "$BASE_URL/v1/transactions/$TXN_ID"
~~~

Expect 202 from POST and normally PROCESSING with processed_at null from the first GET. Poll rather than assuming exactly 30 seconds:

~~~bash
for attempt in 1 2 3 4 5 6 7 8; do
  curl -sS "$BASE_URL/v1/transactions/$TXN_ID"
  sleep 5
done
~~~

The final response must show PROCESSED and a non-null processed_at. Inspect both Daemon logs for the same transaction ID.

Replay the exact payload. Expect 202 with duplicate true. Change amount or an account while keeping the same ID. Expect 409. Send malformed input. Expect 422.

## Measuring 202 latency

Use the existing benchmark only after the public API and both Daemons are healthy:

~~~bash
python scripts/benchmark_webhooks.py \
  --base-url "$BASE_URL" \
  --requests 20 \
  --concurrency 5
~~~

The benchmark measures HTTP acknowledgement latency, not worker completion time. Record the exact date, region, provider plans, concurrency, success count, average, p95, p99, and maximum. Do not reuse local Docker benchmark numbers as cloud results.

A healthy cloud run should be compared with the local assessment target of 500 ms, but the target is not guaranteed on a cold Function, cold Neon compute, or a distant Redis/PostgreSQL region.

## Idempotency verification

Run the existing duplicate script against the public API only when you are comfortable creating test rows in the external database:

~~~bash
python scripts/concurrent_duplicate_test.py \
  --base-url "$BASE_URL" \
  --requests 20
~~~

Confirm:

- all requests receive accepted or duplicate responses;
- exactly one transaction row exists;
- exactly one processing outbox event exists;
- the transaction reaches PROCESSED once;
- a conflicting payload returns 409;
- a repeated completed payload does not increase processing_attempts.

Use a test namespace for IDs.

## Failure and rollout behavior

### Redis outage

The API can durably accept a webhook while Redis is unavailable because the transaction and outbox event are stored in PostgreSQL. The dispatcher retries publication after Redis returns. Readiness should report Redis NOT_READY during the outage.

### Worker outage

If the worker stops during processing, Celery late acknowledgement and the database lease/fencing path protect the transaction. The dispatcher recovery sweep requeues a dispatched event after the 90-second lease expires. Verify attempt count and final status in PostgreSQL.

### Dispatcher outage

Pending outbox rows remain durable. A restarted dispatcher claims and publishes them. Do not replace the dispatcher with a daily Cron Job; a schedule would create a large recovery delay and would not preserve the continuously available outbox bridge.

### Deployment rollout

Vercel sends SIGTERM to old Daemon instances during production rollouts. Celery handles worker shutdown, and the dispatcher now handles SIGTERM with an event-driven stop path. The requested 60-second grace period gives a 30-second task time to finish, but the lease recovery path remains necessary for forced termination.

### Database outage

The API must not return durable-acceptance 202 if PostgreSQL cannot commit. Readiness should fail and the client should retry the webhook after recovery. The outbox cannot recover work that was never committed.

## Hobby usage and pausing

Monitor Vercel Active CPU usage for both Daemons. A mostly idle dispatcher still performs database and TLS operations, and an active worker consumes CPU during task execution. Upstash command usage also needs monitoring because Celery polling can consume free-tier commands.

To pause Daemons, use the Vercel Daemon management UI or deploy an instance count of zero as supported by the configuration reference. Do not delete external databases just to pause the application. Restore one worker and one dispatcher before the next production verification.

## Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| FastAPI build cannot find app | Entrypoint or root changed | Keep root ./, app/main.py, and pyproject.toml entrypoint |
| Daemon build cannot import app | Daemon root is worker-only | Use root . and the shared Dockerfile |
| Daemon configuration rejected | Unsupported field inside Daemon | Keep only documented Daemon fields |
| No worker logs in Preview | Daemons are production-only | Promote a deployment to production before testing |
| API returns 503 readiness | PostgreSQL or Redis URL/TLS/auth issue | Inspect the URL and Vercel Function logs |
| Redis works locally but not Vercel | REST URL or missing TLS | Use a rediss:// TCP URL with certificate validation |
| Database driver import error | Wrong URL dialect | Confirm URL normalization and psycopg installation |
| Migration fails through pooler | Pooler unsuitable for migration/session behavior | Use the direct PostgreSQL URL for Alembic |
| Transaction remains PROCESSING | Daemon stopped, quota, or lease recovery pending | Inspect both Daemon logs and wait beyond 90 seconds |
| 202 latency is high | Cold Function, cold database, region mismatch, throttling | Compare warm/cold runs; do not reuse local results |
| Hobby Daemons stop | Active CPU quota exhausted | Inspect usage and wait for quota reset or use an approved plan |

## Local compatibility verification

Safe checks before a manual deployment:

~~~bash
/usr/bin/python3 -m json.tool vercel.json
.venv/bin/python -c "from app.main import app; from app.workers.celery_app import celery_app; assert app.title; assert 'app.workers.tasks.process_transaction' in celery_app.tasks"
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python -m compileall app tests scripts
docker compose config --quiet
docker build -t transaction-webhook-vercel-daemon-test .
~~~

The image build uses the same root Dockerfile and exercises the shared build context. These checks cannot prove Vercel's remote Daemon rollout, provider connectivity, production quotas, or cloud cold-start latency.

## Security checklist

- Add secrets only in Vercel Production environment variables.
- Use a pooled PostgreSQL URL for application traffic and a direct URL only for reviewed migrations.
- Use a TLS Redis TCP URL and require certificate validation.
- Enable HMAC only after the provider's exact signature contract is implemented.
- Never commit .env, tokens, database passwords, or provider screenshots.
- Use non-production transaction IDs for public smoke tests.
- Review logs for account identifiers and redact sensitive values.
- Confirm the Vercel project is owned by the intended personal account.

## Final manual checklist

Before claiming success, verify all of the following with fresh production evidence:

- [ ] Vercel imports the intended personal repository and main branch.
- [ ] Root directory is ./.
- [ ] FastAPI preset resolves app/main.py.
- [ ] Production environment variables are present.
- [ ] Alembic was applied to the intended external database.
- [ ] External Redis uses a TLS TCP endpoint compatible with Celery.
- [ ] One celery-worker and one outbox-dispatcher Daemon are running.
- [ ] GET / returns 200 HEALTHY.
- [ ] GET /ready returns 200 with both dependencies READY.
- [ ] POST returns 202 and measured latency is recorded.
- [ ] GET first returns PROCESSING.
- [ ] GET later returns PROCESSED with processed_at.
- [ ] Exact replay returns duplicate true.
- [ ] Conflicting replay returns 409.
- [ ] Daemon logs show the transaction lifecycle.
- [ ] Hobby Active CPU and provider quotas are within limits.
- [ ] No deployment claim is made without these observations.

No deployment or provider resource creation is performed by following this documentation alone.

