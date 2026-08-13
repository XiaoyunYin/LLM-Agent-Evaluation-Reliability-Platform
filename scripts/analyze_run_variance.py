"""Measure same-commit run-to-run variability and derive CI thresholds from it.

Answers the question P0 could not: how much does this benchmark move when nothing
changes? Everything here is descriptive over the runs actually executed. With a
handful of repeats there is no distributional claim to make, and none is made — the
spread is reported as an observed range, never as a confidence interval.

Three things it produces:

1. **Variance table** — the metrics a gate might use, across repeats.
2. **Consistency** — per-task pass frequency, and `pass^k` (tasks passing in *every*
   repeat). A benchmark can hold a stable aggregate while individual tasks flip, and
   that is exactly what P0 saw, so consistency is reported separately from accuracy.
3. **Thresholds** — derived by the formula pre-registered in
   `docs/P1_PREREGISTRATION.md` before any of these runs existed:
   `max(2 x observed spread, minimum detectable change)`.

Usage:
    python scripts/analyze_run_variance.py --run spider_rpt__on_1 --run spider_rpt__on_2 ...
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

from backend.app.spider.trajectory import (  # noqa: E402
    DEFAULT_RUN_ROOT,
    TerminationReason,
    TrajectoryStore,
)

ALL_TERMINATIONS = [reason.value for reason in TerminationReason]

# Fields that must match across repeats for them to be a valid repeat set.
IDENTITY_FIELDS = (
    "dataset_version", "split", "model_version", "prompt_version",
    "tool_schema_version", "adapter_version", "agent_version", "max_steps",
    "temperature", "valid_task_count",
)

# Pre-registered in docs/P1_PREREGISTRATION.md, before these runs existed.
SPREAD_MULTIPLIER = 2.0
MIN_DETECTABLE_ACCURACY_PP = 100 / 1034  # one task


def load(run_id: str, root: Path) -> dict[str, Any]:
    store = TrajectoryStore(run_id, root)
    if not store.episodes_path.exists():
        raise SystemExit(f"No episodes for {run_id}")
    config = json.loads(store.config_path.read_text(encoding="utf-8"))
    episodes = {e["task_id"]: e for e in store.iter_episodes()}
    return {"run_id": run_id, "config": config, "episodes": episodes}


def run_metrics(run: dict[str, Any]) -> dict[str, Any]:
    episodes = list(run["episodes"].values())
    total = len(episodes)
    successes = [e for e in episodes if e["termination_reason"] == "SUCCESS"]
    total_cost = sum(e["estimated_cost"] for e in episodes)
    tool_calls = sum(e["tool_steps"] for e in episodes)
    bad_args = sum(e.get("bad_argument_tool_calls", 0) or 0 for e in episodes)

    return {
        "run_id": run["run_id"],
        "episodes": total,
        "passed": len(successes),
        "accuracy": len(successes) / total if total else None,
        "mean_model_turns_per_success": (
            statistics.fmean([e["model_steps"] for e in successes]) if successes else None
        ),
        "mean_trajectory_records_per_success": (
            statistics.fmean([e["total_steps"] for e in successes]) if successes else None
        ),
        "sql_executions": sum(e["sql_executions"] for e in episodes),
        "sql_execution_errors": sum(e["sql_execution_errors"] for e in episodes),
        "sql_execution_error_rate": (
            sum(e["sql_execution_errors"] for e in episodes)
            / sum(e["sql_executions"] for e in episodes)
            if sum(e["sql_executions"] for e in episodes) else None
        ),
        "tool_calls": tool_calls,
        "bad_argument_tool_calls": bad_args,
        "tool_validity_rate": 1 - (bad_args / tool_calls) if tool_calls else None,
        "estimated_cost_total": total_cost,
        "estimated_cost_per_success": total_cost / len(successes) if successes else None,
        "terminations": {
            reason: sum(1 for e in episodes if e["termination_reason"] == reason)
            for reason in ALL_TERMINATIONS
        },
    }


def spread(values: list[float]) -> dict[str, Any]:
    clean = [v for v in values if v is not None]
    if not clean:
        return {"min": None, "max": None, "spread": None, "mean": None, "stdev": None}
    return {
        "min": min(clean),
        "max": max(clean),
        "spread": max(clean) - min(clean),
        "mean": statistics.fmean(clean),
        # Reported for completeness. With a handful of runs this is a descriptive
        # number, not an estimate of a population parameter.
        "stdev": statistics.stdev(clean) if len(clean) > 1 else 0.0,
    }


def analyze(run_ids: list[str], root: Path) -> dict[str, Any]:
    runs = [load(run_id, root) for run_id in run_ids]

    # Repeat-set validity: identical recorded configuration and identical task set.
    reference = runs[0]["config"]
    identity_mismatches = {
        run["run_id"]: {
            field: {"reference": reference.get(field), "this": run["config"].get(field)}
            for field in IDENTITY_FIELDS
            if run["config"].get(field) != reference.get(field)
        }
        for run in runs[1:]
    }
    identity_mismatches = {k: v for k, v in identity_mismatches.items() if v}

    task_sets = [set(run["episodes"]) for run in runs]
    shared = sorted(set.intersection(*task_sets))
    same_task_set = all(ts == task_sets[0] for ts in task_sets)

    commits = {run["run_id"]: run["config"].get("code_commit_sha") for run in runs}
    dirty = {run["run_id"]: run["config"].get("code_working_tree_dirty") for run in runs}
    same_commit = len(set(commits.values())) == 1 and not any(dirty.values())

    metrics = [run_metrics(run) for run in runs]

    # ---- variance table --------------------------------------------------
    gated = {
        "accuracy": [m["accuracy"] for m in metrics],
        "mean_model_turns_per_success": [m["mean_model_turns_per_success"] for m in metrics],
        "mean_trajectory_records_per_success": [
            m["mean_trajectory_records_per_success"] for m in metrics
        ],
        "sql_execution_error_rate": [m["sql_execution_error_rate"] for m in metrics],
        "tool_validity_rate": [m["tool_validity_rate"] for m in metrics],
        "estimated_cost_per_success": [m["estimated_cost_per_success"] for m in metrics],
    }
    variance = {name: spread(values) for name, values in gated.items()}

    # ---- churn between every ordered pair --------------------------------
    def passed(run: dict, task_id: str) -> bool:
        return run["episodes"][task_id]["termination_reason"] == "SUCCESS"

    pairs = []
    for i in range(len(runs)):
        for j in range(i + 1, len(runs)):
            a, b = runs[i], runs[j]
            cells = collections.Counter(
                (passed(a, t), passed(b, t)) for t in shared
            )
            reason_changes = sum(
                1
                for t in shared
                if a["episodes"][t]["termination_reason"]
                != b["episodes"][t]["termination_reason"]
            )
            pass_fail = cells[(True, False)]
            fail_pass = cells[(False, True)]
            pairs.append(
                {
                    "run_a": a["run_id"],
                    "run_b": b["run_id"],
                    "pass_to_pass": cells[(True, True)],
                    "pass_to_fail": pass_fail,
                    "fail_to_pass": fail_pass,
                    "fail_to_fail": cells[(False, False)],
                    "total_pass_fail_flips": pass_fail + fail_pass,
                    "flip_rate": (pass_fail + fail_pass) / len(shared),
                    "termination_reason_changes": reason_changes,
                    "identity_holds": (fail_pass - pass_fail)
                    == (
                        sum(1 for t in shared if passed(b, t))
                        - sum(1 for t in shared if passed(a, t))
                    ),
                }
            )

    # ---- consistency -----------------------------------------------------
    k = len(runs)
    pass_counts = {t: sum(1 for run in runs if passed(run, t)) for t in shared}
    frequency = {t: c / k for t, c in pass_counts.items()}

    always_pass = [t for t, c in pass_counts.items() if c == k]
    always_fail = [t for t, c in pass_counts.items() if c == 0]
    flaky = [t for t, c in pass_counts.items() if 0 < c < k]

    consistency = {
        "repeats_k": k,
        "definitions": {
            "pass_pow_k": "Share of tasks passing in EVERY one of the k repeats.",
            "pass_at_k": "Share of tasks passing in AT LEAST ONE of the k repeats.",
            "flaky": "Share passing in some but not all repeats.",
        },
        "pass_pow_k": len(always_pass) / len(shared),
        "pass_at_k": (len(shared) - len(always_fail)) / len(shared),
        "always_fail": len(always_fail) / len(shared),
        "flaky_share": len(flaky) / len(shared),
        "counts": {
            "always_pass": len(always_pass),
            "always_fail": len(always_fail),
            "flaky": len(flaky),
            "tasks": len(shared),
        },
        "pass_frequency_histogram": dict(
            sorted(collections.Counter(pass_counts.values()).items())
        ),
        "gap_mean_accuracy_minus_pass_pow_k": (
            statistics.fmean([m["accuracy"] for m in metrics]) - len(always_pass) / len(shared)
        ),
        "flaky_task_ids": sorted(flaky),
        "high_churn_tasks": sorted(
            (
                {"task_id": t, "passes": pass_counts[t], "of": k, "frequency": frequency[t]}
                for t in flaky
            ),
            key=lambda row: abs(row["frequency"] - 0.5),
        )[:40],
    }

    # ---- thresholds (formula pre-registered) -----------------------------
    thresholds = {}
    for name, block in variance.items():
        if block["spread"] is None:
            continue
        observed = block["spread"]
        floor = MIN_DETECTABLE_ACCURACY_PP / 100 if name == "accuracy" else 0.0
        thresholds[name] = {
            "observed_spread": observed,
            "threshold": max(SPREAD_MULTIPLIER * observed, floor),
            "formula": f"max({SPREAD_MULTIPLIER} x spread, minimum_detectable_change)",
            "units": "absolute difference in the metric",
        }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runs": run_ids,
        "repeat_set_validity": {
            "identical_recorded_configuration": not identity_mismatches,
            "config_mismatches": identity_mismatches,
            "identical_task_set": same_task_set,
            "shared_tasks": len(shared),
            "same_commit_clean_tree": same_commit,
            "commits": commits,
            "working_tree_dirty": dirty,
        },
        "per_run_metrics": metrics,
        "variance": variance,
        "pairwise_churn": pairs,
        "churn_summary": {
            "pairs": len(pairs),
            "mean_pass_fail_flips": statistics.fmean(
                [p["total_pass_fail_flips"] for p in pairs]
            ) if pairs else None,
            "max_pass_fail_flips": max((p["total_pass_fail_flips"] for p in pairs), default=None),
            "mean_reason_changes": statistics.fmean(
                [p["termination_reason_changes"] for p in pairs]
            ) if pairs else None,
            "all_identities_hold": all(p["identity_holds"] for p in pairs),
        },
        "consistency": consistency,
        "ci_thresholds": thresholds,
        "threshold_policy": (
            "max(2 x observed spread, minimum detectable change), fixed in "
            "docs/P1_PREREGISTRATION.md before these runs existed. A policy choice "
            "derived from a measured envelope, NOT a statistical guarantee."
        ),
        "not_claimed": [
            f"No confidence interval: k={k} repeats is a descriptive range, not a sample.",
            "No distributional assumption about the accuracy of future runs.",
        ],
    }


def print_report(report: dict[str, Any]) -> None:
    validity = report["repeat_set_validity"]
    print(f"Run-to-run variance over {len(report['runs'])} runs\n")
    print("REPEAT-SET VALIDITY")
    print(f"  identical recorded configuration : {validity['identical_recorded_configuration']}")
    print(f"  identical task set               : {validity['identical_task_set']} "
          f"({validity['shared_tasks']:,} tasks)")
    print(f"  same commit, clean tree          : {validity['same_commit_clean_tree']}")
    if validity["config_mismatches"]:
        print(f"  MISMATCHES: {validity['config_mismatches']}")
    print()

    print("PER-RUN METRICS")
    header = f"{'run':<22}{'passed':>8}{'accuracy':>10}{'turns/succ':>12}{'sqlerr':>9}{'$/succ':>11}"
    print(header)
    for m in report["per_run_metrics"]:
        print(f"{m['run_id']:<22}{m['passed']:>8,}{m['accuracy']:>10.4f}"
              f"{m['mean_model_turns_per_success']:>12.3f}"
              f"{m['sql_execution_error_rate']:>9.4f}"
              f"{m['estimated_cost_per_success']:>11.6f}")
    print()

    print("VARIANCE  (observed range across repeats; not a confidence interval)")
    print(f"{'metric':<38}{'min':>12}{'max':>12}{'spread':>12}")
    for name, block in report["variance"].items():
        if block["spread"] is None:
            continue
        print(f"{name:<38}{block['min']:>12.6f}{block['max']:>12.6f}{block['spread']:>12.6f}")
    print()

    churn = report["churn_summary"]
    print("PAIRWISE CHURN")
    print(f"  pairs compared           {churn['pairs']}")
    print(f"  mean pass/fail flips     {churn['mean_pass_fail_flips']:.1f}")
    print(f"  max pass/fail flips      {churn['max_pass_fail_flips']}")
    print(f"  mean reason changes      {churn['mean_reason_changes']:.1f}")
    print(f"  all identities hold      {churn['all_identities_hold']}")
    print()

    consistency = report["consistency"]
    print(f"CONSISTENCY  (k={consistency['repeats_k']})")
    print(f"  pass^k  (pass in every repeat)   {consistency['pass_pow_k']:.4f} "
          f"({consistency['counts']['always_pass']:,} tasks)")
    print(f"  pass@k  (pass in at least one)   {consistency['pass_at_k']:.4f}")
    print(f"  always fail                      {consistency['always_fail']:.4f} "
          f"({consistency['counts']['always_fail']:,} tasks)")
    print(f"  flaky                            {consistency['flaky_share']:.4f} "
          f"({consistency['counts']['flaky']:,} tasks)")
    print(f"  mean accuracy - pass^k           "
          f"{consistency['gap_mean_accuracy_minus_pass_pow_k']:+.4f}")
    print(f"  pass-frequency histogram         {consistency['pass_frequency_histogram']}")
    print()

    print("CI THRESHOLDS  (formula pre-registered before these runs)")
    print(f"{'metric':<38}{'spread':>12}{'threshold':>14}")
    for name, block in report["ci_thresholds"].items():
        print(f"{name:<38}{block['observed_spread']:>12.6f}{block['threshold']:>14.6f}")
    print()
    print(f"  policy: {report['threshold_policy']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="append", dest="runs", required=True)
    parser.add_argument("--root", default=str(DEFAULT_RUN_ROOT))
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    report = analyze(args.runs, Path(args.root))
    print_report(report)

    output = Path(args.output) if args.output else (
        REPO_ROOT / "runs" / "spider_variance" / "variance_report.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
