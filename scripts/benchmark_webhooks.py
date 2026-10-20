#!/usr/bin/env python3
"""Measure webhook acknowledgement latency; completion time is intentionally separate."""

import argparse
import asyncio
import math
import statistics
import time
import uuid

import httpx


async def send(client: httpx.AsyncClient, base_url: str, index: int) -> tuple[int, float]:
    payload = {
        "transaction_id": f"txn_bench_{uuid.uuid4().hex}_{index}",
        "source_account": "acc_user_789",
        "destination_account": "acc_merchant_456",
        "amount": "1500.00",
        "currency": "INR",
    }
    started = time.perf_counter()
    response = await client.post(f"{base_url}/v1/webhooks/transactions", json=payload)
    return response.status_code, (time.perf_counter() - started) * 1000


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--requests", type=int, default=50)
    parser.add_argument("--concurrency", type=int, default=20)
    args = parser.parse_args()
    limits = httpx.Limits(max_connections=args.concurrency)
    semaphore = asyncio.Semaphore(args.concurrency)

    async with httpx.AsyncClient(limits=limits, timeout=10) as client:

        async def bounded(index: int):
            async with semaphore:
                return await send(client, args.base_url, index)

        batch_started = time.perf_counter()
        results = await asyncio.gather(*(bounded(i) for i in range(args.requests)))
        batch_elapsed_seconds = time.perf_counter() - batch_started
    latencies = sorted(latency for code, latency in results if code == 202)
    failures = len(results) - len(latencies)

    def percentile(fraction: float) -> float:
        if not latencies:
            return 0
        index = min(len(latencies) - 1, max(0, math.ceil(len(latencies) * fraction) - 1))
        return latencies[index]

    print(f"requests={len(results)} success={len(latencies)} failure={failures}")
    if latencies:
        print(
            f"avg_ms={statistics.mean(latencies):.2f} "
            f"p50_ms={percentile(0.50):.2f} p95_ms={percentile(0.95):.2f} "
            f"p99_ms={percentile(0.99):.2f} max_ms={max(latencies):.2f}"
        )
        print(
            f"batch_elapsed_ms={batch_elapsed_seconds * 1000:.2f} "
            f"accepted_per_second={len(latencies) / batch_elapsed_seconds:.2f} "
            "(client-observed aggregate)"
        )


if __name__ == "__main__":
    asyncio.run(main())
