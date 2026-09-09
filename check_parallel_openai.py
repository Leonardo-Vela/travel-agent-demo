"""Stress-test the OpenAI API with sustained concurrent agent-like loops.

This simulates multiple users/agents, each repeatedly calling the API in a loop,
which is closer to real world usage than a single-shot concurrency probe.

Examples:
    python check_parallel_openai.py
    python check_parallel_openai.py --concurrency 20 --iterations 8
    python check_parallel_openai.py --concurrency 30 --iterations 12 --model gpt-4o-mini
"""

from __future__ import annotations

import argparse
import concurrent.futures
import math
import os
import statistics
import time
from pathlib import Path

from openai import OpenAI


ROOT = Path(__file__).resolve().parent


def _load_key_and_model() -> tuple[str, str]:
    """Resolve the OpenAI key from env or project secrets."""

    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    if api_key:
        return api_key.strip(), model.strip()

    secrets_path = ROOT / ".streamlit" / "secrets.toml"
    if secrets_path.exists():
        for line in secrets_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("OPENAI_API_KEY"):
                _, raw = stripped.split("=", 1)
                api_key = raw.strip().strip('"').strip("'")
            elif stripped.startswith("OPENAI_MODEL"):
                _, raw = stripped.split("=", 1)
                model = raw.strip().strip('"').strip("'")
        if api_key:
            return api_key, model

    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
        api_key = os.getenv("OPENAI_API_KEY")
        model = os.getenv("OPENAI_MODEL", model)
    except Exception:
        pass

    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Add it to Streamlit secrets or export it in your environment."
        )

    return api_key.strip(), model.strip()


def run_agent_loop(worker_id: int, client: OpenAI, model: str, iterations: int) -> list[dict]:
    results: list[dict] = []
    for step in range(iterations):
        prompt = (
            f"Worker {worker_id} loop step {step}: "
            "Return exactly: ok. Keep the response minimal and valid."
        )
        start = time.perf_counter()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a minimal responder."},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=12,
        )
        elapsed = time.perf_counter() - start
        text = (response.choices[0].message.content or "").strip()
        results.append(
            {
                "worker": worker_id,
                "step": step,
                "ok": text.lower() == "ok",
                "elapsed_sec": round(elapsed, 3),
                "text": text,
            }
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Stress-test concurrent OpenAI agent loops.")
    parser.add_argument("--concurrency", type=int, default=30)
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    api_key, resolved_model = _load_key_and_model()
    model = args.model or resolved_model
    client = OpenAI(api_key=api_key)

    total_requests = args.concurrency * args.iterations
    print(
        f"Running sustained stress test: concurrency={args.concurrency}, "
        f"iterations={args.iterations}, total_requests={total_requests}, model={model}"
    )
    start = time.perf_counter()

    all_results: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [
            executor.submit(run_agent_loop, worker_id, client, model, args.iterations)
            for worker_id in range(args.concurrency)
        ]
        for future in concurrent.futures.as_completed(futures):
            all_results.extend(future.result())

    total_time = time.perf_counter() - start
    successful = [item for item in all_results if item["ok"]]
    failed = [item for item in all_results if not item["ok"]]
    elapsed_values = [item["elapsed_sec"] for item in all_results]
    avg_latency = statistics.mean(elapsed_values) if elapsed_values else 0.0
    p95 = sorted(elapsed_values)[max(0, math.ceil(0.95 * len(elapsed_values)) - 1)] if elapsed_values else 0.0
    rps = total_requests / total_time if total_time > 0 else 0.0

    print(f"Completed in {total_time:.2f}s")
    print(f"Successful calls: {len(successful)}/{total_requests}")
    print(f"Failed calls: {len(failed)}")
    print(f"Average latency per request: {avg_latency:.3f}s")
    print(f"P95 latency: {p95:.3f}s")
    print(f"Throughput: {rps:.2f} requests/sec")

    if failed:
        print("Sample failures:")
        for item in failed[:10]:
            print(item)
        return 1

    print("All sustained concurrent agent-loop calls succeeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
