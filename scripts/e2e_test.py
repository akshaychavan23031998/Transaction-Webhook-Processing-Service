#!/usr/bin/env python3
"""Run the real-stack acceptance flow against a running API."""

import argparse
import time
from datetime import UTC, datetime

import httpx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--transaction-id", default=f"txn_e2e_{int(time.time())}")
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()
    payload = {
        "transaction_id": args.transaction_id,
        "source_account": "acc_user_789",
        "destination_account": "acc_merchant_456",
        "amount": 1500,
        "currency": "INR",
    }
    with httpx.Client(base_url=args.base_url, timeout=10) as client:
        started = time.perf_counter()
        accepted = client.post("/v1/webhooks/transactions", json=payload)
        latency_ms = (time.perf_counter() - started) * 1000
        print(f"webhook status={accepted.status_code} latency_ms={latency_ms:.2f}")
        print(f"initial response={accepted.json()}")
        assert accepted.status_code == 202
        initial = client.get(f"/v1/transactions/{args.transaction_id}")
        print(f"initial transaction={initial.json()}")
        assert initial.json()["status"] == "PROCESSING"

        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            current = client.get(f"/v1/transactions/{args.transaction_id}").json()
            if current["status"] == "PROCESSED":
                print(f"processed_at={current['processed_at']}")
                break
            time.sleep(1)
        else:
            raise SystemExit("transaction did not reach PROCESSED before timeout")

        duplicate = client.post("/v1/webhooks/transactions", json=payload)
        print(f"duplicate status={duplicate.status_code} response={duplicate.json()}")
        assert duplicate.status_code == 202
        assert duplicate.json()["duplicate"] is True
        print(f"completed_at={datetime.now(UTC).isoformat()}")


if __name__ == "__main__":
    main()
