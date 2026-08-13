"""Freeze the schema-repair cohort from the baselines, before any treatment run.

The cohort rule is pre-registered in docs/P3_REPAIR_PREREGISTRATION.md §6: tasks
that produced at least one invalid typed call in **at least 3 of the 10** baseline
runs, with a floor of 8 tasks or the experiment is reported underpowered.

The ≥3 threshold exists to keep regression to the mean from masquerading as a
treatment effect. A cohort defined by a single occurrence would be largely made of
tasks that were never going to provoke a second one, and any follow-up measurement
would show "improvement" with no treatment applied at all.

Freezing happens before treatment for the same reason the P2 cohort was frozen
first: a cohort chosen after seeing both arms is a choice about the answer.

    python -m scripts.freeze_p3_cohort --runs support_b2_01 ...
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.p3_repair_metrics import load_arm  # noqa: E402

MANIFEST = REPO_ROOT / "config" / "p3_frozen_manifest.json"
OUTPUT = REPO_ROOT / "config" / "p3_repair_cohort.json"
MIN_RUNS_WITH_INVALID = 3
MIN_COHORT_SIZE = 8


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", nargs="+", required=True)
    args = parser.parse_args()

    frozen = json.loads(MANIFEST.read_text(encoding="utf-8"))
    episodes, excluded = load_arm(args.runs, frozen["task_count"])
    for note in excluded:
        print(f"EXCLUDED {note}")
    runs = sorted({e["run_id"] for e in episodes})
    if not runs:
        print("no usable runs")
        return 1

    runs_with_invalid = Counter()
    total_invalid = Counter()
    for episode in episodes:
        if episode["invalid_calls"] > 0:
            runs_with_invalid[episode["task_id"]] += 1
            total_invalid[episode["task_id"]] += episode["invalid_calls"]

    cohort = sorted(t for t, n in runs_with_invalid.items() if n >= MIN_RUNS_WITH_INVALID)

    print(f"runs used {len(runs)}  episodes {len(episodes)}")
    print(f"tasks provoking >=1 invalid call in >=1 run: {len(runs_with_invalid)}")
    print(f"cohort (>= {MIN_RUNS_WITH_INVALID} of {len(runs)} runs): {len(cohort)}\n")
    for task_id in cohort:
        print(f"  {task_id:<26} {runs_with_invalid[task_id]}/{len(runs)} runs, "
              f"{total_invalid[task_id]} invalid calls")

    underpowered = len(cohort) < MIN_COHORT_SIZE
    if underpowered:
        print(f"\nUNDERPOWERED: {len(cohort)} < {MIN_COHORT_SIZE} required. "
              "The experiment is reported underpowered rather than run to a number.")

    payload = {
        "frozen_from_runs": runs,
        "suite_sha256": frozen["suite_sha256"],
        "rule": f">=1 invalid typed call in >= {MIN_RUNS_WITH_INVALID} of {len(runs)} baseline runs",
        "min_cohort_size": MIN_COHORT_SIZE,
        "underpowered": underpowered,
        "cohort_size": len(cohort),
        "cohort": cohort,
        "baseline_counts": {
            t: {"runs_with_invalid": runs_with_invalid[t], "invalid_calls": total_invalid[t]}
            for t in cohort
        },
        "all_tasks_with_any_invalid": {
            t: runs_with_invalid[t] for t in sorted(runs_with_invalid)
        },
    }
    OUTPUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
