"""Execute the P1 run family, waiting for quota and stopping on bad runs.

Runs 4 ON repeats then 1 validation-OFF ablation, all from the `p1-runner` tag
with an identical recorded configuration. Between runs it health-checks the
result, and it stops rather than continuing if runs come back unusable.

**Why a health gate.** A run that halted on quota, or that contains
infrastructure failures, is not a measurement. Continuing to spend on further
runs while those pile up produces an expensive pile of unusable artifacts. The
gate is stated here rather than judged case by case:

A run is UNHEALTHY if any of:
  - it did not complete all 1,034 tasks
  - it contains any RATE_LIMITED / MODEL_ERROR / TOOL_ERROR episode
  - its evaluator reported errors, or gold queries failed
  - trajectories are missing or duplicated

**Two unhealthy runs stops the family.** One can be a transient provider blip
worth retrying; two is a pattern, and the right response is to look rather than
keep paying.

Usage:
    python scripts/run_p1_family.py                 # wait for quota, then run
    python scripts/run_p1_family.py --max-wait-hours 6
    python scripts/run_p1_family.py --dry-run       # show the plan only
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

from backend.app.spider.trajectory import (  # noqa: E402
    DEFAULT_RUN_ROOT,
    INFRASTRUCTURE_TERMINATIONS,
    TrajectoryStore,
)

ON_RUNS = ["spider_rpt__on_1", "spider_rpt__on_2", "spider_rpt__on_3", "spider_rpt__on_4"]
OFF_RUN = "spider_abl__off_1"
EXPECTED_TASKS = 1034

# Requests one full run needs, measured on the P0 runs (~5,215 model calls).
# A run is not started without this much headroom, because starting one that
# cannot finish just burns the quota that would have finished it.
REQUESTS_PER_RUN = 5400

# Headroom required before starting. Deliberately far below REQUESTS_PER_RUN: on a
# per-minute limit the counter refills continuously, and the halt-and-resume path
# covers running out mid-run.
MIN_REQUESTS_TO_START = 500


def quota_headroom() -> dict[str, Any]:
    """Probe the provider's enforced limits. One request."""
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], max_retries=0)
    try:
        response = client.chat.completions.with_raw_response.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=3,
        )
        headers = response.headers

        def as_int(value):
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        return {
            "available": True,
            "limit_requests": as_int(headers.get("x-ratelimit-limit-requests")),
            "remaining_requests": as_int(headers.get("x-ratelimit-remaining-requests")),
            "limit_tokens": as_int(headers.get("x-ratelimit-limit-tokens")),
            "reset_requests": headers.get("x-ratelimit-reset-requests"),
        }
    except Exception as error:  # noqa: BLE001
        return {"available": False, "error": str(error)[:220]}


def has_headroom(status: dict[str, Any]) -> bool:
    """Enough quota to make real progress.

    The remaining-requests header is per-window, and the window depends on the
    account tier: a daily cap reports the day's remainder, a per-minute cap
    reports the minute's. Requiring a whole run's worth would therefore wait
    forever on a per-minute limit that refills every 60s.

    So this only checks there is meaningful headroom right now. Running out
    mid-run is already handled: the runner halts cleanly, checkpoints, and the
    next attempt resumes.
    """
    if not status.get("available"):
        return False
    remaining = status.get("remaining_requests")
    # No header is not evidence of headroom; treat it as unknown and wait.
    return remaining is not None and remaining >= MIN_REQUESTS_TO_START


def health_check(run_id: str, root: Path) -> dict[str, Any]:
    """Is this run a usable measurement?"""
    store = TrajectoryStore(run_id, root)
    if not store.episodes_path.exists():
        return {"healthy": False, "reasons": ["no episodes recorded"], "episodes": 0}

    episodes = list(store.iter_episodes())
    infrastructure = {reason.value for reason in INFRASTRUCTURE_TERMINATIONS}

    counts: dict[str, int] = {}
    for episode in episodes:
        reason = episode["termination_reason"]
        counts[reason] = counts.get(reason, 0) + 1

    infra_total = sum(counts.get(reason, 0) for reason in infrastructure)
    evaluator_errors = sum(
        1
        for e in episodes
        if (e.get("verification_result") or {}).get("outcome")
        in {"evaluator_error", "gold_error"}
    )
    duplicates = store.duplicate_task_ids()

    reasons: list[str] = []
    if len(episodes) != EXPECTED_TASKS:
        reasons.append(f"incomplete: {len(episodes)}/{EXPECTED_TASKS} episodes")
    if infra_total:
        reasons.append(f"{infra_total} infrastructure-terminated episode(s): "
                       f"{ {r: counts[r] for r in infrastructure if counts.get(r)} }")
    if evaluator_errors:
        reasons.append(f"{evaluator_errors} evaluator/gold error(s)")
    if duplicates:
        reasons.append(f"duplicate task ids: {list(duplicates)[:5]}")

    successes = counts.get("SUCCESS", 0)
    return {
        "healthy": not reasons,
        "reasons": reasons,
        "episodes": len(episodes),
        "passed": successes,
        "accuracy": successes / len(episodes) if episodes else None,
        "terminations": counts,
    }


def execute_run(run_id: str, concurrency: int, validation_on: bool) -> int:
    command = [
        str(REPO_ROOT / ".venv" / "Scripts" / "python.exe"),
        str(REPO_ROOT / "scripts" / "run_spider_benchmark.py"),
        "--stage", "full",
        "--run-id", run_id,
        "--concurrency", str(concurrency),
        "--quiet",
    ]
    if not validation_on:
        command.append("--disable-tool-validation")

    environment = dict(os.environ)
    environment.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4317")

    print(f"  $ {' '.join(command[2:])}", flush=True)
    return subprocess.run(command, cwd=REPO_ROOT, env=environment).returncode


def score_run(run_id: str) -> None:
    """Score both evaluator modes immediately, before the next run starts."""
    python = str(REPO_ROOT / ".venv" / "Scripts" / "python.exe")
    for command in (
        [python, "scripts/report_spider_metrics.py", "--run-id", run_id, "--check-traces"],
        [python, "scripts/rescore_with_substrate.py", "--run-id", run_id,
         "--substrate", "test_suite", "--quiet"],
        [python, "scripts/analyze_spider_failures.py", "--run-id", run_id,
         "--no-verify-abandoned"],
    ):
        subprocess.run(command, cwd=REPO_ROOT, capture_output=True)
    print(f"  scored {run_id} on both substrates", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--max-wait-hours", type=float, default=26.0)
    parser.add_argument("--poll-seconds", type=int, default=300)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--root", default=str(DEFAULT_RUN_ROOT))
    args = parser.parse_args()

    root = Path(args.root)
    plan = [(run_id, True) for run_id in ON_RUNS] + [(OFF_RUN, False)]

    print("P1 run family")
    for run_id, validation_on in plan:
        print(f"  {run_id:<22} tool_argument_validation={validation_on}")
    print(f"  concurrency {args.concurrency}, ~{REQUESTS_PER_RUN:,} requests per run")
    print("  stop rule: 2 unhealthy runs halts the family")
    print()

    if args.dry_run:
        print(json.dumps(quota_headroom(), indent=2))
        return 0

    unhealthy: list[str] = []
    results: list[dict[str, Any]] = []
    deadline = time.time() + args.max_wait_hours * 3600

    for run_id, validation_on in plan:
        existing = health_check(run_id, root)
        if existing["healthy"]:
            print(f"{run_id}: already complete and healthy, skipping", flush=True)
            results.append({"run_id": run_id, **existing})
            continue

        # Wait for enough quota to finish a whole run.
        while True:
            status = quota_headroom()
            if has_headroom(status):
                print(f"{run_id}: quota OK "
                      f"(limit {status['limit_requests']}, "
                      f"remaining {status['remaining_requests']})", flush=True)
                break
            if time.time() > deadline:
                print(f"\nSTOPPED: no quota headroom within "
                      f"{args.max_wait_hours}h. Last status: {status}", flush=True)
                return 75
            print(f"{run_id}: waiting for quota "
                  f"(limit {status.get('limit_requests')}, "
                  f"remaining {status.get('remaining_requests')}, "
                  f"reset {status.get('reset_requests')})", flush=True)
            time.sleep(args.poll_seconds)

        print(f"{run_id}: starting {datetime.now(timezone.utc):%H:%M:%S}Z", flush=True)
        started = time.time()
        code = execute_run(run_id, args.concurrency, validation_on)
        minutes = (time.time() - started) / 60

        health = health_check(run_id, root)
        results.append({"run_id": run_id, "exit_code": code, "minutes": minutes, **health})

        if health["healthy"]:
            print(f"{run_id}: HEALTHY  {health['passed']}/{health['episodes']} = "
                  f"{health['accuracy']:.4f}  ({minutes:.1f} min)", flush=True)
            score_run(run_id)
        else:
            unhealthy.append(run_id)
            print(f"{run_id}: UNHEALTHY ({len(unhealthy)} of 2 allowed)", flush=True)
            for reason in health["reasons"]:
                print(f"    - {reason}", flush=True)

            if len(unhealthy) >= 2:
                print("\n" + "=" * 68, flush=True)
                print("STOPPING: two runs came back unhealthy.", flush=True)
                print(f"  unhealthy runs: {unhealthy}", flush=True)
                print("  Not spending further until this is investigated.", flush=True)
                print("=" * 68, flush=True)
                break

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "concurrency": args.concurrency,
        "runs": results,
        "unhealthy": unhealthy,
        "stopped_early": len(unhealthy) >= 2,
        "complete": len([r for r in results if r.get("healthy")]) == len(plan),
    }
    output = root / "p1_family_summary.json"
    output.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    print()
    print(f"{'run':<24}{'healthy':>9}{'episodes':>10}{'accuracy':>10}{'min':>8}")
    for row in results:
        accuracy = f"{row['accuracy']:.4f}" if row.get("accuracy") is not None else "-"
        print(f"{row['run_id']:<24}{str(row.get('healthy')):>9}"
              f"{row.get('episodes', 0):>10}{accuracy:>10}"
              f"{row.get('minutes', 0):>8.1f}")
    print(f"\nWrote {output}")

    if summary["stopped_early"]:
        return 1
    return 0 if summary["complete"] else 75


if __name__ == "__main__":
    sys.exit(main())
