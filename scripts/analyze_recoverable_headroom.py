"""Find every failed episode that already executed a passing query.

P1 asked this only of `MAX_STEPS` episodes, which was too narrow. An episode that
*submitted* an answer and failed verification may still have run a correct query
earlier and then chosen a worse one — a different defect with a different fix, and
invisible if you only look at agents that ran out of turns.

So this searches **all** failed episodes and splits what it finds:

- `FOUND_PASSING_NEVER_SUBMITTED` — a correct query was executed and no answer was
  submitted. A termination/confidence problem.
- `FOUND_PASSING_SUBMITTED_WORSE` — a correct query was executed and a different,
  wrong one was submitted. A candidate-selection problem.

Those two want different interventions, which is the reason for separating them
before designing either.

Verdicts come from the **test-suite** evaluator throughout, so "passing" means
passing the stricter metric and the headroom is not inflated by single-database
false positives.

Usage:
    python scripts/analyze_recoverable_headroom.py --run spider_rpt__on_1 ...
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.spider.evaluator import (  # noqa: E402
    SUBSTRATE_TEST_SUITE,
    VerificationOutcome,
    substrate_database_path,
    verify_sql,
)
from backend.app.spider.loader import load_spider_tasks  # noqa: E402
from backend.app.spider.trajectory import (  # noqa: E402
    DEFAULT_RUN_ROOT,
    TrajectoryStore,
    open_jsonl,
)

NEVER_SUBMITTED = "FOUND_PASSING_NEVER_SUBMITTED"
SUBMITTED_WORSE = "FOUND_PASSING_SUBMITTED_WORSE"


def normalize(query: str) -> str:
    return " ".join((query or "").lower().replace(";", " ").split())


def analyze_run(run_id: str, root: Path, tasks: dict, verbose: bool) -> dict[str, Any]:
    store = TrajectoryStore(run_id, root)
    config = json.loads(store.config_path.read_text(encoding="utf-8"))

    rescore_path = store.run_dir / f"rescore__{SUBSTRATE_TEST_SUITE}.json"
    if not rescore_path.exists():
        raise SystemExit(f"No test-suite rescore for {run_id}")
    verdicts = {
        row["task_id"]: row
        for row in json.loads(rescore_path.read_text(encoding="utf-8"))["per_task"]
    }

    episodes = {e["episode_id"]: e for e in store.iter_episodes()}
    steps_by_episode: dict[str, list[dict]] = collections.defaultdict(list)
    for step in store.iter_steps():
        steps_by_episode[step["episode_id"]].append(step)

    tool_results: dict[str, Any] = {}
    with open_jsonl(store.payloads_path) as handle:
        for line in handle:
            line = line.strip()
            if not line or '"tool_result"' not in line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("kind") == "tool_result":
                tool_results[record["ref"]] = record.get("data") or {}

    findings: list[dict[str, Any]] = []
    failed = 0

    for index, episode in enumerate(episodes.values(), start=1):
        task_id = episode["task_id"]
        verdict = verdicts.get(task_id) or {}
        # Failure under the STRICT metric, which is what the headroom is about.
        if verdict.get("rescored_passed"):
            continue
        failed += 1

        task = tasks[task_id]
        ordered = sorted(steps_by_episode[episode["episode_id"]],
                         key=lambda s: s["step_index"])

        model_turn_of_step: dict[int, int] = {}
        turn = 0
        for step in ordered:
            if step["step_type"] == "model":
                turn += 1
            model_turn_of_step[step["step_index"]] = turn

        executions = [
            (step, tool_results.get(step["tool_result_ref"]) or {})
            for step in ordered
            if step["tool_name"] == "execute_sql"
        ]

        first_pass = None
        for position, (step, result) in enumerate(executions, start=1):
            query = (step.get("tool_args") or {}).get("query")
            if not query:
                continue
            verification = verify_sql(
                query,
                task.gold_query,
                substrate_database_path(task.database_id, SUBSTRATE_TEST_SUITE),
                task_id,
                task.database_id,
                substrate=SUBSTRATE_TEST_SUITE,
            )
            if verification.outcome is VerificationOutcome.PASS:
                first_pass = (position, step, result, query)
                break

        if first_pass is None:
            continue

        position, step, result, query = first_pass
        final_sql = episode.get("final_sql")
        subtype = NEVER_SUBMITTED if not final_sql else SUBMITTED_WORSE

        later = [normalize((s.get("tool_args") or {}).get("query", ""))
                 for s, _ in executions[position:]]
        later_results = [
            json.dumps(r.get("rows"), sort_keys=True, default=str)
            for _, r in executions[position:]
        ]
        this_result = json.dumps(result.get("rows"), sort_keys=True, default=str)
        row_count = result.get("row_count")
        max_steps = config.get("max_steps") or 10
        first_turn = model_turn_of_step.get(step["step_index"])

        findings.append(
            {
                "run_id": run_id,
                "task_id": task_id,
                "database_id": task.database_id,
                "subtype": subtype,
                "termination_reason": episode["termination_reason"],
                "passing_query": query,
                "submitted_query": final_sql,
                "passing_result_row_count": row_count,
                "passing_result_was_empty": row_count == 0,
                "first_passing_at_model_turn": first_turn,
                "first_passing_at_sql_call": position,
                "total_sql_calls": len(executions),
                "model_turns_used": episode["model_steps"],
                "model_turns_remaining_after": max(max_steps - (first_turn or 0), 0),
                "equivalent_query_repeated_later": normalize(query) in later,
                "identical_result_set_repeated_later": this_result in later_results,
            }
        )

        if verbose and index % 200 == 0:
            print(f"  {run_id}: {index}/{len(episodes)} scanned, "
                  f"{len(findings)} recoverable", flush=True)

    return {
        "run_id": run_id,
        "tool_argument_validation": config.get("tool_argument_validation"),
        "episodes": len(episodes),
        "failed_under_test_suite": failed,
        "recoverable": len(findings),
        "by_subtype": dict(collections.Counter(f["subtype"] for f in findings)),
        "by_termination": dict(collections.Counter(f["termination_reason"] for f in findings)),
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="append", dest="runs", required=True)
    parser.add_argument("--root", default=str(DEFAULT_RUN_ROOT))
    parser.add_argument("--output", default=None)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    root = Path(args.root)
    tasks = {t.task_id: t for t in load_spider_tasks("dev")}

    per_run = []
    for run_id in args.runs:
        print(f"scanning {run_id} ...", flush=True)
        per_run.append(analyze_run(run_id, root, tasks, not args.quiet))
        latest = per_run[-1]
        print(f"  failed {latest['failed_under_test_suite']}, "
              f"recoverable {latest['recoverable']} {latest['by_subtype']}", flush=True)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "substrate": SUBSTRATE_TEST_SUITE,
        "definition": {
            NEVER_SUBMITTED: (
                "A failed episode executed a query that passes the test-suite "
                "evaluator and submitted no final answer."
            ),
            SUBMITTED_WORSE: (
                "A failed episode executed a query that passes the test-suite "
                "evaluator and then submitted a different, failing one."
            ),
        },
        "runs": per_run,
    }

    output = Path(args.output) if args.output else (
        REPO_ROOT / "runs" / "spider_variance" / "recoverable_headroom.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print()
    print(f"{'run':<22}{'failed':>8}{'recover':>9}{'never_sub':>11}{'sub_worse':>11}")
    for run in per_run:
        print(f"{run['run_id']:<22}{run['failed_under_test_suite']:>8}"
              f"{run['recoverable']:>9}"
              f"{run['by_subtype'].get(NEVER_SUBMITTED, 0):>11}"
              f"{run['by_subtype'].get(SUBMITTED_WORSE, 0):>11}")
    print(f"\nWrote {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
