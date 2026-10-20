#!/usr/bin/env python3
"""Submit one immutable webhook concurrently and verify duplicate acknowledgements."""

import argparse
import asyncio
import time
import uuid

import httpx


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--requests", type=int, default=20)
    args = parser.parse_args()
    payload = {
        "transaction_id": f"txn_concurrent_{uuid.uuid4().hex}",
        "source_account": "acc_user_789",
        "destination_account": "acc_merchant_456",
        "amount": "1500.00",
        "currency": "INR",
    }
    async with httpx.AsyncClient(base_url=args.base_url, timeout=10) as client:
        started = time.perf_counter()
        responses = await asyncio.gather(
            *(client.post("/v1/webhooks/transactions", json=payload) for _ in range(args.requests))
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
    bodies = [response.json() for response in responses]
    statuses = [response.status_code for response in responses]
    duplicate_flags = [body["duplicate"] for body in bodies]
    print(f"requests={len(responses)} statuses={sorted(set(statuses))} elapsed_ms={elapsed_ms:.2f}")
    print(
        "new_acceptances="
        f"{duplicate_flags.count(False)} duplicate_acceptances={duplicate_flags.count(True)}"
    )
    assert statuses == [202] * args.requests
    assert duplicate_flags.count(False) == 1


if __name__ == "__main__":
    asyncio.run(main())
