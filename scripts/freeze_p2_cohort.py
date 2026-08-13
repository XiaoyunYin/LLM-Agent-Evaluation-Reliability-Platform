"""Build and freeze the P2 target cohort from baseline behaviour only.

The cohort is the union of tasks that showed a recoverable failure in at least one
baseline run. Freezing it **before** any treatment exists is what stops the target
being redrawn around whatever the treatment happened to fix.

It also carries, per task, the baseline pass frequency across the repeated runs.
Those labels are descriptive. **A 0/5 task is not proven deterministically
unsolvable** — five samples cannot establish that, and P1 already measured 6.5% of
tasks flipping between identical runs. The labels are for describing the cohort,
not for inference.

Usage:
    python scripts/freeze_p2_cohort.py
"""

from __future__ import annotations

import argparse
import collections
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.spider.evaluator import SUBSTRATE_TEST_SUITE  # noqa: E402
from backend.app.spider.trajectory import DEFAULT_RUN_ROOT, TrajectoryStore  # noqa: E402

HEADROOM = REPO_ROOT / "runs" / "spider_variance" / "recoverable_headroom.json"
COHORT = REPO_ROOT / "runs" / "spider_variance" / "p2_cohort_frozen.json"

NEVER_SUBMITTED = "FOUND_PASSING_NEVER_SUBMITTED"
SUBMITTED_WORSE = "FOUND_PASSING_SUBMITTED_WORSE"

# The clean same-configuration family. The OFF ablation is a baseline in the sense
# that it precedes treatment, but its configuration differs, so pass frequency is
# reported over both groupings rather than silently mixing them.
ON_RUNS = ["spider_rpt__on_1", "spider_rpt__on_2", "spider_rpt__on_3", "spider_rpt__on_4"]
OFF_RUN = "spider_abl__off_1"


def load_verdicts(run_id: str, root: Path) -> dict[str, bool]:
    store = TrajectoryStore(run_id, root)
    path = store.run_dir / f"rescore__{SUBSTRATE_TEST_SUITE}.json"
    return {
        row["task_id"]: bool(row["rescored_passed"])
        for row in json.loads(path.read_text(encoding="utf-8"))["per_task"]
    }


def load_empty_execution_tasks(run_id: str, root: Path) -> set[str]:
    """Tasks whose trajectory contains at least one successful EMPTY execution.

    Needed for the non-target damage cohort: the intervention changes how an empty
    result is read, so the tasks at risk are the ones that saw an empty result and
    were NOT recoverable.
    """
    store = TrajectoryStore(run_id, root)
    from backend.app.spider.trajectory import open_jsonl

    results: dict[str, Any] = {}
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
                results[record["ref"]] = record.get("data") or {}

    episode_task = {e["episode_id"]: e["task_id"] for e in store.iter_episodes()}
    tasks: set[str] = set()
    for step in store.iter_steps():
        if step.get("tool_name") != "execute_sql":
            continue
        data = results.get(step.get("tool_result_ref")) or {}
        if data.get("row_count") == 0 and data.get("error") is None:
            task_id = episode_task.get(step["episode_id"])
            if task_id:
                tasks.add(task_id)
    return tasks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(DEFAULT_RUN_ROOT))
    args = parser.parse_args()
    root = Path(args.root)

    if not HEADROOM.exists():
        raise SystemExit(f"Run scripts/analyze_recoverable_headroom.py first ({HEADROOM})")
    headroom = json.loads(HEADROOM.read_text(encoding="utf-8"))

    all_runs = ON_RUNS + [OFF_RUN]
    verdicts = {run_id: load_verdicts(run_id, root) for run_id in all_runs}
    empty_tasks = {run_id: load_empty_execution_tasks(run_id, root) for run_id in all_runs}

    # ---- per-task ledger -------------------------------------------------
    by_task: dict[str, list[dict]] = collections.defaultdict(list)
    for run in headroom["runs"]:
        for finding in run["findings"]:
            by_task[finding["task_id"]].append(finding)

    cohort: list[dict[str, Any]] = []
    for task_id, findings in sorted(by_task.items()):
        subtypes = collections.Counter(f["subtype"] for f in findings)
        passes_5 = sum(1 for r in all_runs if verdicts[r].get(task_id))
        passes_on = sum(1 for r in ON_RUNS if verdicts[r].get(task_id))

        cohort.append(
            {
                "task_id": task_id,
                "database_id": findings[0]["database_id"],
                "runs_with_recoverable_failure": len(findings),
                "of_runs": len(all_runs),
                "subtype_frequency": dict(subtypes),
                "dominant_subtype": subtypes.most_common(1)[0][0],
                "mixed_subtype": len(subtypes) > 1,
                "passing_result_empty_count": sum(
                    1 for f in findings if f["passing_result_was_empty"]
                ),
                "passing_result_always_empty": all(
                    f["passing_result_was_empty"] for f in findings
                ),
                "first_passing_turn_min": min(
                    f["first_passing_at_model_turn"] for f in findings
                ),
                "first_passing_turn_median": statistics.median(
                    [f["first_passing_at_model_turn"] for f in findings]
                ),
                "turns_remaining_after_median": statistics.median(
                    [f["model_turns_remaining_after"] for f in findings]
                ),
                "equivalent_query_repeated_count": sum(
                    1 for f in findings if f["equivalent_query_repeated_later"]
                ),
                "identical_result_repeated_count": sum(
                    1 for f in findings if f["identical_result_set_repeated_later"]
                ),
                "baseline_pass_frequency_5runs": f"{passes_5}/5",
                "baseline_pass_frequency_on_only": f"{passes_on}/4",
                "termination_reasons": dict(
                    collections.Counter(f["termination_reason"] for f in findings)
                ),
            }
        )

    # ---- non-target damage cohort ---------------------------------------
    cohort_ids = {row["task_id"] for row in cohort}
    non_target: dict[str, int] = collections.Counter()
    for run_id in all_runs:
        for task_id in empty_tasks[run_id]:
            if task_id not in cohort_ids:
                non_target[task_id] += 1

    # ---- summary ---------------------------------------------------------
    per_run_recoverable = [r["recoverable"] for r in headroom["runs"]]
    frequency_5 = collections.Counter(row["baseline_pass_frequency_5runs"] for row in cohort)
    frequency_on = collections.Counter(row["baseline_pass_frequency_on_only"] for row in cohort)

    report = {
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "substrate": SUBSTRATE_TEST_SUITE,
        "baseline_runs": all_runs,
        "note_on_off_run": (
            f"{OFF_RUN} ran with tool_argument_validation=false. It precedes "
            "treatment so it contributes to cohort discovery, but pass frequency "
            "is reported over both the 5-run and the clean 4-run ON groupings."
        ),
        "cohort_definition": (
            "Union of tasks that showed a recoverable failure - a failed episode "
            "that had already executed a query passing the test-suite evaluator - "
            "in at least one baseline run."
        ),
        "frozen": True,
        "must_not_be_modified": (
            "This cohort is frozen before any treatment exists. Redrawing it after "
            "treatment results appear would make the target a function of the "
            "result."
        ),
        "cohort_size": len(cohort),
        "observed_recoverable_per_run": {
            "counts": per_run_recoverable,
            "min": min(per_run_recoverable),
            "max": max(per_run_recoverable),
            "mean": statistics.fmean(per_run_recoverable),
            "as_share_of_1034": statistics.fmean(per_run_recoverable) / 1034,
            "mean_pp": 100 * statistics.fmean(per_run_recoverable) / 1034,
        },
        "subtype_totals": dict(
            collections.Counter(
                f["subtype"] for run in headroom["runs"] for f in run["findings"]
            )
        ),
        "cohort_by_dominant_subtype": dict(
            collections.Counter(row["dominant_subtype"] for row in cohort)
        ),
        "recurrence": dict(
            collections.Counter(row["runs_with_recoverable_failure"] for row in cohort)
        ),
        "baseline_pass_frequency_histogram_5runs": dict(sorted(frequency_5.items())),
        "baseline_pass_frequency_histogram_on_only": dict(sorted(frequency_on.items())),
        "pass_frequency_caveat": (
            "Descriptive labels. A 0/5 task is NOT proven deterministically "
            "unsolvable - five samples cannot establish that, and P1 measured 6.5% "
            "of tasks flipping between identical runs. Inference must rest on "
            "pooled paired behaviour, not on these labels."
        ),
        "empty_result_profile": {
            "cohort_tasks_always_empty": sum(
                1 for row in cohort if row["passing_result_always_empty"]
            ),
            "cohort_tasks_ever_empty": sum(
                1 for row in cohort if row["passing_result_empty_count"] > 0
            ),
        },
        "non_target_empty_result_cohort": {
            "definition": (
                "Tasks NOT in the frozen cohort whose baseline trajectories contain "
                "at least one successful EMPTY execution. These are what an "
                "empty-result intervention could damage."
            ),
            "size": len(non_target),
            "task_ids": sorted(non_target),
        },
        "cohort": cohort,
    }

    COHORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print(f"P2 cohort frozen: {len(cohort)} tasks")
    print(f"  recoverable per run     {per_run_recoverable} "
          f"(mean {report['observed_recoverable_per_run']['mean']:.1f} = "
          f"{report['observed_recoverable_per_run']['mean_pp']:.2f}pp)")
    print(f"  dominant subtype        {report['cohort_by_dominant_subtype']}")
    print(f"  subtype totals          {report['subtype_totals']}")
    print(f"  recurrence (runs/task)  {report['recurrence']}")
    print(f"  pass freq (5 runs)      {report['baseline_pass_frequency_histogram_5runs']}")
    print(f"  pass freq (ON only)     {report['baseline_pass_frequency_histogram_on_only']}")
    print(f"  always-empty passing    "
          f"{report['empty_result_profile']['cohort_tasks_always_empty']}/{len(cohort)}")
    print(f"  non-target damage cohort {report['non_target_empty_result_cohort']['size']}")
    print(f"\nWrote {COHORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
