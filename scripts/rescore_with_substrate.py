"""Rescore a finished run's persisted SQL against a different database substrate.

No model is re-run. The agent's submitted SQL is already on disk in
`episodes.jsonl`, so a second metric can be computed over exactly the same
trajectories. That matters: the single-database and test-suite numbers then
describe one identical set of agent behaviours, and any difference between them is
the metric, not the agent.

**The original metric is never overwritten.** Output goes to
`rescore__<substrate>.json` beside the run, and `p0_metrics.json` is untouched.

**Denominators can differ between substrates.** A gold query that fails on some
distilled instance is excluded from the test-suite metric only; the
single-database metric keeps its full denominator. Both are reported.

Usage:
    python scripts/rescore_with_substrate.py --run-id spider_full__p0_v2 \\
                                             --substrate test_suite
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.spider.evaluator import (  # noqa: E402
    SUBSTRATE_DISPLAY_NAMES,
    SUBSTRATE_METRIC_IDS,
    SUBSTRATE_SINGLE_DB,
    SUBSTRATE_TEST_SUITE,
    VerificationOutcome,
    substrate_database_path,
    verify_sql,
)
from backend.app.spider.loader import load_spider_tasks  # noqa: E402
from backend.app.spider.trajectory import DEFAULT_RUN_ROOT, TrajectoryStore  # noqa: E402

QA_DIR = REPO_ROOT / "runs" / "spider_verifier_qa"


def substrate_exclusions(substrate: str) -> dict[str, str]:
    """Tasks whose gold query fails on this substrate, from that substrate's QA.

    These are excluded from this substrate's metric only. Silently scoring a task
    whose gold cannot pass would charge the agent for a benchmark defect.
    """
    suffix = "" if substrate == SUBSTRATE_SINGLE_DB else f"__{substrate}"
    path = QA_DIR / f"verifier_qa_dev{suffix}.json"
    if not path.exists():
        raise SystemExit(
            f"No verifier QA for substrate {substrate!r} at {path}. Run:\n"
            f"  python scripts/qa_spider_evaluator.py --split dev --substrate {substrate}"
        )
    report = json.loads(path.read_text(encoding="utf-8"))
    return {
        failure["task_id"]: failure.get("error") or failure["outcome"]
        for failure in report["gold_pass"]["failures"]
    }


def rescore(run_id: str, root: Path, substrate: str, verbose: bool) -> dict[str, Any]:
    store = TrajectoryStore(run_id, root)
    if not store.episodes_path.exists():
        raise SystemExit(f"No episodes for {run_id}")

    config = json.loads(store.config_path.read_text(encoding="utf-8"))
    episodes = list(store.iter_episodes())
    tasks = {t.task_id: t for t in load_spider_tasks(config.get("split") or "dev")}
    excluded = substrate_exclusions(substrate)

    started = time.perf_counter()
    per_task: list[dict[str, Any]] = []

    for index, episode in enumerate(episodes, start=1):
        task_id = episode["task_id"]
        task = tasks[task_id]
        original = (episode.get("verification_result") or {}).get("passed")
        final_sql = episode.get("final_sql")

        if task_id in excluded:
            per_task.append(
                {
                    "task_id": task_id,
                    "database_id": task.database_id,
                    "excluded_on_this_substrate": True,
                    "exclusion_reason": excluded[task_id],
                    "original_passed": original,
                    "rescored_passed": None,
                    "outcome": "excluded",
                }
            )
            continue

        result = verify_sql(
            predicted_sql=final_sql,
            gold_sql=task.gold_query,
            database_path=substrate_database_path(task.database_id, substrate),
            task_id=task_id,
            database_id=task.database_id,
            substrate=substrate,
        )
        per_task.append(
            {
                "task_id": task_id,
                "database_id": task.database_id,
                "excluded_on_this_substrate": False,
                "original_passed": original,
                "rescored_passed": result.passed,
                "outcome": result.outcome.value,
                "substrate_instances": result.substrate_instances,
                "final_sql": final_sql,
            }
        )

        if verbose and index % 100 == 0:
            scored = [r for r in per_task if not r["excluded_on_this_substrate"]]
            passing = sum(1 for r in scored if r["rescored_passed"])
            print(f"  {index}/{len(episodes)}  passing {passing}/{len(scored)}")

    scored = [r for r in per_task if not r["excluded_on_this_substrate"]]
    passed = sum(1 for r in scored if r["rescored_passed"])

    # Movement against the run's own original metric, restricted to tasks scored
    # on both substrates so the comparison has a common denominator.
    comparable = [
        r for r in scored
        if r["original_passed"] is not None and r["rescored_passed"] is not None
    ]
    pass_to_fail = [r for r in comparable if r["original_passed"] and not r["rescored_passed"]]
    fail_to_pass = [r for r in comparable if not r["original_passed"] and r["rescored_passed"]]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "substrate": substrate,
        "metric": SUBSTRATE_METRIC_IDS[substrate],
        "metric_display_name": SUBSTRATE_DISPLAY_NAMES[substrate],
        "model_rerun": False,
        "scored_from": (
            "final_sql persisted in episodes.jsonl - no model call was made, so this "
            "metric describes exactly the same trajectories as the original"
        ),
        "config": {
            key: config.get(key)
            for key in (
                "model_version", "prompt_version", "tool_schema_version",
                "dataset_version", "code_commit_sha", "max_steps", "temperature",
            )
        },
        "denominator": {
            "episodes_in_run": len(episodes),
            "excluded_on_this_substrate": len(per_task) - len(scored),
            "scored": len(scored),
            "note": (
                "Exclusions apply to THIS substrate only. The single-database metric "
                "keeps its own denominator and is not affected."
            ),
        },
        "result": {
            "passed": passed,
            "scored": len(scored),
            "accuracy": passed / len(scored) if scored else None,
        },
        "movement_vs_original_metric": {
            "comparable_tasks": len(comparable),
            "pass_to_fail": len(pass_to_fail),
            "fail_to_pass": len(fail_to_pass),
            "net": len(fail_to_pass) - len(pass_to_fail),
            "pass_to_fail_task_ids": sorted(r["task_id"] for r in pass_to_fail),
            "fail_to_pass_task_ids": sorted(r["task_id"] for r in fail_to_pass),
            "interpretation": (
                "pass_to_fail are answers the single-database metric credited that "
                "the tighter substrate rejects - the false positives the original "
                "metric could not see. fail_to_pass should be rare and is worth "
                "inspecting if it is not."
            ),
        },
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "per_task": per_task,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--root", default=str(DEFAULT_RUN_ROOT))
    parser.add_argument(
        "--substrate", default=SUBSTRATE_TEST_SUITE,
        choices=[SUBSTRATE_SINGLE_DB, SUBSTRATE_TEST_SUITE],
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    report = rescore(args.run_id, Path(args.root), args.substrate, not args.quiet)

    result = report["result"]
    movement = report["movement_vs_original_metric"]
    denominator = report["denominator"]

    print()
    print(f"Rescored {report['run_id']} on substrate '{report['substrate']}'")
    print(f"  metric               {report['metric']}")
    print(f"  episodes in run      {denominator['episodes_in_run']:,}")
    print(f"  excluded here        {denominator['excluded_on_this_substrate']:,}")
    print(f"  scored               {denominator['scored']:,}")
    print(f"  passed               {result['passed']:,}/{result['scored']:,} "
          f"= {result['accuracy']:.4f}" if result["accuracy"] is not None else "  no tasks")
    print()
    print(f"  vs the run's original metric ({movement['comparable_tasks']:,} comparable):")
    print(f"    pass -> fail       {movement['pass_to_fail']:,}   "
          f"(credited by single-DB, rejected here)")
    print(f"    fail -> pass       {movement['fail_to_pass']:,}")
    print(f"    net                {movement['net']:+d}")

    output = Path(args.root) / args.run_id / f"rescore__{args.substrate}.json"
    output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
