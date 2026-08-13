"""Apply the pre-registered P2 verdict to the treatment runs.

Everything here was fixed in `docs/P2_PREREGISTRATION.md` before the treatment
existed: the cohort, the primary metric, the adoption bar, the damage threshold,
and the no-regression guards. This script only evaluates them.

Inference is **paired over task-run cells**, not over the global accuracy delta.
The frozen cohort is 39 of 1,034 tasks, so even a complete fix moves global
accuracy by ~3pp, which sits inside twice the P1 noise envelope. Judging the
intervention globally would return inconclusive whether or not it worked.

Usage:
    python scripts/analyze_p2_treatment.py
"""

from __future__ import annotations

import argparse
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

COHORT_PATH = REPO_ROOT / "runs" / "spider_variance" / "p2_cohort_frozen.json"
GATE_PATH = REPO_ROOT / "metrics" / "spider_gate_policy.json"
OUTPUT = REPO_ROOT / "runs" / "spider_variance" / "p2_verdict.json"

ON_RUNS = ["spider_rpt__on_1", "spider_rpt__on_2", "spider_rpt__on_3", "spider_rpt__on_4"]
BRIDGE = "spider_p2__bridge_control"
TREATMENTS = ["spider_p2__treat_1", "spider_p2__treat_2", "spider_p2__treat_3"]

# Pre-registered constants, from docs/P2_PREREGISTRATION.md.
COHORT_ON_MAX = 0.2821
DAMAGE_FLOOR = 0.1846
BRIDGE_REGION = (0.6093, 0.6770)
DISCORDANCE_BAR = 44


def verdicts(run_id: str, root: Path) -> dict[str, bool]:
    path = TrajectoryStore(run_id, root).run_dir / f"rescore__{SUBSTRATE_TEST_SUITE}.json"
    return {
        row["task_id"]: bool(row["rescored_passed"])
        for row in json.loads(path.read_text(encoding="utf-8"))["per_task"]
    }


def guard_metrics(run_id: str, root: Path, passes: dict[str, bool]) -> dict[str, Any]:
    store = TrajectoryStore(run_id, root)
    episodes = list(store.iter_episodes())
    successes = [e for e in episodes if passes.get(e["task_id"])]
    total_cost = sum(e["estimated_cost"] for e in episodes)
    tool_calls = sum(e["tool_steps"] for e in episodes)
    bad_args = sum(e.get("bad_argument_tool_calls", 0) or 0 for e in episodes)
    return {
        "test_suite_accuracy": sum(passes.values()) / len(episodes),
        "mean_model_turns_per_success": (
            statistics.fmean([e["model_steps"] for e in successes]) if successes else None
        ),
        "tool_validity_rate": 1 - (bad_args / tool_calls) if tool_calls else None,
        "estimated_cost_per_success": total_cost / len(successes) if successes else None,
        "max_steps": sum(1 for e in episodes if e["termination_reason"] == "MAX_STEPS"),
        "empty_successful_executions": sum(
            e.get("empty_successful_executions", 0) or 0 for e in episodes
        ),
        "submitted_immediately_after_empty": sum(
            e.get("submitted_immediately_after_empty", 0) or 0 for e in episodes
        ),
        "infrastructure_episodes": sum(
            1 for e in episodes
            if e["termination_reason"] in {"RATE_LIMITED", "MODEL_ERROR", "TOOL_ERROR"}
        ),
        "episodes": len(episodes),
        "duplicates": len(store.duplicate_task_ids()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(DEFAULT_RUN_ROOT))
    args = parser.parse_args()
    root = Path(args.root)

    cohort_doc = json.loads(COHORT_PATH.read_text(encoding="utf-8"))
    cohort = [row["task_id"] for row in cohort_doc["cohort"]]
    non_target = cohort_doc["non_target_empty_result_cohort"]["task_ids"]
    gates = json.loads(GATE_PATH.read_text(encoding="utf-8"))["gate"]["metrics"]

    baseline = {run_id: verdicts(run_id, root) for run_id in ON_RUNS}
    bridge = verdicts(BRIDGE, root)
    treatment = {run_id: verdicts(run_id, root) for run_id in TREATMENTS}

    def rate(passes: dict[str, bool], tasks: list[str]) -> float:
        return sum(1 for t in tasks if passes.get(t)) / len(tasks)

    # ---- primary: cohort conversion --------------------------------------
    baseline_rates = [rate(baseline[r], cohort) for r in ON_RUNS]
    bridge_rate = rate(bridge, cohort)
    treatment_rates = {r: rate(treatment[r], cohort) for r in TREATMENTS}

    pooled_baseline = statistics.fmean(baseline_rates)
    pooled_treatment = statistics.fmean(treatment_rates.values())

    # ---- pooled paired cells --------------------------------------------
    # Each cohort task contributes its baseline pass frequency against each
    # treatment run's outcome; conversions and regressions are counted per cell.
    conversions = regressions = 0
    per_task: list[dict[str, Any]] = []
    for task_id in cohort:
        base_passes = sum(1 for r in ON_RUNS if baseline[r].get(task_id))
        treat_passes = sum(1 for r in TREATMENTS if treatment[r].get(task_id))
        base_rate = base_passes / len(ON_RUNS)
        treat_rate = treat_passes / len(TREATMENTS)
        if treat_rate > base_rate:
            conversions += 1
        elif treat_rate < base_rate:
            regressions += 1
        per_task.append(
            {
                "task_id": task_id,
                "baseline_passes": f"{base_passes}/{len(ON_RUNS)}",
                "treatment_passes": f"{treat_passes}/{len(TREATMENTS)}",
                "baseline_rate": base_rate,
                "treatment_rate": treat_rate,
                "direction": (
                    "converted" if treat_rate > base_rate
                    else "regressed" if treat_rate < base_rate else "unchanged"
                ),
            }
        )

    # ---- damage channel --------------------------------------------------
    damage_baseline = [rate(baseline[r], non_target) for r in ON_RUNS]
    damage_treatment = {r: rate(treatment[r], non_target) for r in TREATMENTS}
    damage_breaches = {
        r: v for r, v in damage_treatment.items() if v < DAMAGE_FLOOR
    }

    # ---- guards ----------------------------------------------------------
    guard_baseline = {r: guard_metrics(r, root, baseline[r]) for r in ON_RUNS}
    guard_treatment = {r: guard_metrics(r, root, treatment[r]) for r in TREATMENTS}

    def guard_check(name: str, key: str, direction: str) -> dict[str, Any]:
        threshold = gates[name]["threshold"]
        base_values = [guard_baseline[r][key] for r in ON_RUNS]
        worst_base = min(base_values) if direction == "decrease_is_bad" else max(base_values)
        breaches = {}
        for r in TREATMENTS:
            value = guard_treatment[r][key]
            if direction == "decrease_is_bad":
                if worst_base - value > threshold:
                    breaches[r] = value
            else:
                if value - worst_base > threshold:
                    breaches[r] = value
        return {
            "threshold": threshold,
            "baseline_worst": worst_base,
            "treatment_values": {r: guard_treatment[r][key] for r in TREATMENTS},
            "breaches": breaches,
            "holds": not breaches,
        }

    guards = {
        "test_suite_task_success": guard_check(
            "test_suite_task_success", "test_suite_accuracy", "decrease_is_bad"),
        "mean_model_turns_per_success": guard_check(
            "mean_model_turns_per_success", "mean_model_turns_per_success", "increase_is_bad"),
        "tool_validity_rate": guard_check(
            "tool_validity_rate", "tool_validity_rate", "decrease_is_bad"),
        "estimated_cost_per_success": guard_check(
            "estimated_cost_per_success", "estimated_cost_per_success", "increase_is_bad"),
    }
    infrastructure_clean = all(
        guard_treatment[r]["infrastructure_episodes"] == 0
        and guard_treatment[r]["duplicates"] == 0
        and guard_treatment[r]["episodes"] == 1034
        for r in TREATMENTS
    )

    # ---- pre-registered verdict -----------------------------------------
    condition_1 = all(v > COHORT_ON_MAX for v in treatment_rates.values())
    condition_2 = conversions > regressions
    condition_3 = all(g["holds"] for g in guards.values()) and infrastructure_clean
    condition_4 = not damage_breaches

    if condition_1 and condition_2 and condition_3 and condition_4:
        verdict = "ADOPT"
    elif condition_2 and condition_3:
        verdict = "ITERATE"
    else:
        verdict = "DROP"

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "preregistration": "docs/P2_PREREGISTRATION.md",
        "substrate": SUBSTRATE_TEST_SUITE,
        "cohort_size": len(cohort),
        "primary": {
            "metric": "recoverable_cohort_conversion_rate",
            "baseline_rates_on": dict(zip(ON_RUNS, baseline_rates)),
            "pooled_baseline": pooled_baseline,
            "bridge_rate": bridge_rate,
            "treatment_rates": treatment_rates,
            "pooled_treatment": pooled_treatment,
            "absolute_change": pooled_treatment - pooled_baseline,
            "on_max_bar": COHORT_ON_MAX,
        },
        "paired_cells": {
            "converted_tasks": conversions,
            "regressed_tasks": regressions,
            "unchanged_tasks": len(cohort) - conversions - regressions,
            "net": conversions - regressions,
            "per_task": per_task,
        },
        "damage_channel": {
            "non_target_cohort_size": len(non_target),
            "baseline_rates": dict(zip(ON_RUNS, damage_baseline)),
            "pooled_baseline": statistics.fmean(damage_baseline),
            "treatment_rates": damage_treatment,
            "floor": DAMAGE_FLOOR,
            "breaches": damage_breaches,
            "holds": not damage_breaches,
            "premature_empty_submissions": {
                "baseline": {r: guard_baseline[r]["submitted_immediately_after_empty"] for r in ON_RUNS},
                "treatment": {r: guard_treatment[r]["submitted_immediately_after_empty"] for r in TREATMENTS},
            },
        },
        "guards": guards,
        "infrastructure_clean": infrastructure_clean,
        "secondary": {
            "max_steps": {
                "baseline": {r: guard_baseline[r]["max_steps"] for r in ON_RUNS},
                "treatment": {r: guard_treatment[r]["max_steps"] for r in TREATMENTS},
            },
            "full_suite_accuracy": {
                "baseline": {r: guard_baseline[r]["test_suite_accuracy"] for r in ON_RUNS},
                "bridge": bridge_rate and guard_metrics(BRIDGE, root, bridge)["test_suite_accuracy"],
                "treatment": {r: guard_treatment[r]["test_suite_accuracy"] for r in TREATMENTS},
            },
        },
        "conditions": {
            "1_every_treatment_run_clears_on_max": condition_1,
            "2_pooled_conversions_exceed_regressions": condition_2,
            "3_no_regression_guards_hold": condition_3,
            "4_damage_within_threshold": condition_4,
        },
        "verdict": verdict,
    }

    OUTPUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    p = report["primary"]
    print("P2 TREATMENT VERDICT  (rules fixed before the treatment existed)\n")
    print("PRIMARY - recoverable cohort conversion rate")
    print(f"  baseline ON runs   {[f'{v:.4f}' for v in baseline_rates]}  pooled {pooled_baseline:.4f}")
    print(f"  bridge control     {bridge_rate:.4f}")
    print(f"  treatment runs     {[f'{v:.4f}' for v in treatment_rates.values()]}  pooled {pooled_treatment:.4f}")
    print(f"  absolute change    {p['absolute_change']:+.4f}")
    print(f"  bar (ON max)       {COHORT_ON_MAX:.4f}")
    print()
    print("PAIRED CELLS")
    print(f"  converted {conversions}  regressed {regressions}  "
          f"unchanged {len(cohort)-conversions-regressions}  net {conversions-regressions:+d}")
    print()
    print("DAMAGE CHANNEL (non-target empty-result cohort)")
    print(f"  baseline pooled    {statistics.fmean(damage_baseline):.4f}")
    print(f"  treatment          {[f'{v:.4f}' for v in damage_treatment.values()]}")
    print(f"  floor              {DAMAGE_FLOOR:.4f}   breaches: {damage_breaches or 'none'}")
    print()
    print("NO-REGRESSION GUARDS")
    for name, g in guards.items():
        print(f"  {'ok  ' if g['holds'] else 'FAIL'} {name:<32} "
              f"base {g['baseline_worst']:.5f} -> {[f'{v:.5f}' for v in g['treatment_values'].values()]}")
    print(f"  {'ok  ' if infrastructure_clean else 'FAIL'} infrastructure clean")
    print()
    for name, ok in report["conditions"].items():
        print(f"  condition {name}: {ok}")
    print()
    print(f"VERDICT: {verdict}")
    print(f"\nWrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
