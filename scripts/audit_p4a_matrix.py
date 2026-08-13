"""Audit a P4a deterministic matrix artifact against frozen task definitions.

The matrix runner writes enough row-level evidence to prove its accounting. This
script reconstructs the expected clean and crash cases from the frozen P3 task
definitions and verifies the artifact row-for-row, including all absolute
acceptance counters.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.support.durability import CrashWindow  # noqa: E402
from backend.app.support.tools import EFFECTFUL_TOOLS  # noqa: E402
from scripts.run_p4a_matrix import enumerate_cases, selected_entries  # noqa: E402


ARTIFACT = REPO_ROOT / "runs" / "p4a_matrix" / "p4a_matrix_20260813" / "p4a_matrix.json"
ZERO_ACCEPTANCE_COUNTERS = {
    "duplicate_side_effects",
    "lost_required_effects",
    "incorrect_final_states",
    "stale_fenced_effects_accepted",
    "orphan_effect_records",
    "invariant_violations",
}
ZERO_INVARIANTS = {
    "durable_intent_duplicates",
    "effect_result_duplicates",
    "effects_without_intent",
    "completed_without_result",
    "stale_fenced_effects_accepted",
    "duplicate_business_mutations",
}


def _case_key(row: dict[str, Any]) -> tuple[str, str, str | None, int | None, str | None]:
    return (
        row["task_id"],
        row["case_id"],
        row["crash_window"],
        row["step_index"],
        row["tool_name"],
    )


def _expected_key(case: Any) -> tuple[str, str, str | None, int | None, str | None]:
    return (
        case.task_id,
        case.case_id,
        case.crash_window,
        case.step_index,
        case.tool_name,
    )


def audit(artifact: Path = ARTIFACT) -> dict[str, Any]:
    report = json.loads(artifact.read_text(encoding="utf-8"))
    rows = report["cases"]
    expected_cases = [case for case, _entry in enumerate_cases(selected_entries(None))]

    actual_counts = Counter(_case_key(row) for row in rows)
    expected_counts = Counter(_expected_key(case) for case in expected_cases)
    duplicate_actual = [key for key, count in actual_counts.items() if count != 1]
    duplicate_expected = [key for key, count in expected_counts.items() if count != 1]
    missing = sorted(expected_counts.keys() - actual_counts.keys())
    unexpected = sorted(actual_counts.keys() - expected_counts.keys())

    expected_crash_windows = {window.value for window in CrashWindow}
    expected_effectful_step_count = sum(
        1
        for case in expected_cases
        if case.crash_window == CrashWindow.BEFORE_INTENT_INSERT.value
    )
    by_window = Counter(row["crash_window"] or "clean" for row in rows)
    by_tool_window: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        if row["crash_window"] is not None:
            by_tool_window[row["tool_name"]][row["crash_window"]] += 1

    row_acceptance_nonzero = []
    row_invariant_nonzero = []
    row_verification_failures = []
    row_effect_count_mismatches = []
    row_not_passed = []
    for row in rows:
        for key in ZERO_ACCEPTANCE_COUNTERS:
            if int(row["acceptance_counts"][key]) != 0:
                row_acceptance_nonzero.append((row["case_id"], key, row["acceptance_counts"][key]))
        for key in ZERO_INVARIANTS:
            if int(row["invariants"][key]) != 0:
                row_invariant_nonzero.append((row["case_id"], key, row["invariants"][key]))
        if not row["verification"]["passed"]:
            row_verification_failures.append(row["case_id"])
        if row["actual_effect_records"] != row["expected_effect_records"]:
            row_effect_count_mismatches.append(row["case_id"])
        if not row["passed"]:
            row_not_passed.append(row["case_id"])

    summary = report["summary"]
    summary_acceptance_nonzero = {
        key: value for key, value in summary["acceptance_totals"].items() if int(value) != 0
    }
    crash_row_count = sum(1 for row in rows if row["crash_window"] is not None)
    clean_row_count = sum(1 for row in rows if row["crash_window"] is None)

    semantics = {
        "crash_before_intent_cases": by_window[CrashWindow.BEFORE_INTENT_INSERT.value],
        "crash_after_intent_cases": by_window[CrashWindow.AFTER_INTENT_BEFORE_EFFECT.value],
        "crash_inside_before_effect_application_cases": by_window[
            CrashWindow.INSIDE_BEFORE_EFFECT_APPLICATION.value
        ],
        "crash_after_effect_before_runner_completion_cases": by_window[
            CrashWindow.AFTER_EFFECT_BEFORE_STEP_COMPLETION.value
        ],
        "crash_after_step_before_next_model_cases": by_window[
            CrashWindow.AFTER_STEP_BEFORE_NEXT_MODEL.value
        ],
        "retry_of_persisted_intent_cases": sum(
            1
            for row in rows
            if row["crash_window"] == CrashWindow.AFTER_INTENT_BEFORE_EFFECT.value
            and row["crash_observed"]
            and row["intent_records"] >= 1
            and row["passed"]
        ),
        "stale_worker_fencing_cases_in_matrix": sum(
            1 for row in rows if row["stale_token_attempts"] > 0
        ),
        "poison_dlq_cases_in_matrix": sum(1 for row in rows if row["runner_state"] == "DLQ"),
    }

    failures = {
        "duplicate_actual_case_keys": duplicate_actual,
        "duplicate_expected_case_keys": duplicate_expected,
        "missing_expected_cases": missing,
        "unexpected_cases": unexpected,
        "row_acceptance_nonzero": row_acceptance_nonzero,
        "row_invariant_nonzero": row_invariant_nonzero,
        "row_verification_failures": row_verification_failures,
        "row_effect_count_mismatches": row_effect_count_mismatches,
        "row_not_passed": row_not_passed,
        "summary_acceptance_nonzero": summary_acceptance_nonzero,
    }
    accounting = {
        "clean_cases": clean_row_count,
        "crash_cases": crash_row_count,
        "total_cases": len(rows),
        "passed_cases": sum(1 for row in rows if row["passed"]),
        "expected_clean_cases": 80,
        "expected_effectful_steps": expected_effectful_step_count,
        "expected_crash_cases": expected_effectful_step_count * len(expected_crash_windows),
        "expected_total_cases": 80 + expected_effectful_step_count * len(expected_crash_windows),
        "summary_clean_cases": summary["clean_cases"],
        "summary_crash_cases": summary["crash_cases"],
        "summary_total_cases": summary["cases"],
        "summary_passed_cases": summary["passed_cases"],
        "by_window": dict(sorted(by_window.items())),
        "by_tool_window": {
            tool: dict(sorted(windows.items())) for tool, windows in sorted(by_tool_window.items())
        },
    }
    expected_accounting = (
        clean_row_count == 80
        and crash_row_count == 835
        and len(rows) == 915
        and sum(1 for row in rows if row["passed"]) == 915
        and summary["clean_cases"] == 80
        and summary["crash_cases"] == 835
        and summary["cases"] == 915
        and summary["passed_cases"] == 915
        and set(by_window) == expected_crash_windows | {"clean"}
        and by_window["clean"] == 80
        and all(by_window[window] == expected_effectful_step_count for window in expected_crash_windows)
    )

    all_checks_passed = expected_accounting and all(not value for value in failures.values())
    return {
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "artifact": str(artifact),
        "artifact_run_id": report["run_id"],
        "model_calls_made": report["model_calls_made"],
        "accounting": accounting,
        "acceptance_counters_checked": sorted(ZERO_ACCEPTANCE_COUNTERS),
        "protocol_invariants_checked": sorted(ZERO_INVARIANTS),
        "recovery_semantics": semantics,
        "failures": failures,
        "all_checks_passed": all_checks_passed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, default=ARTIFACT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = audit(args.artifact)
    output = args.output or args.artifact.with_name("p4a_matrix_audit.json")
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"P4a matrix audit: {result['artifact_run_id']}")
    print(f"  all_checks_passed {result['all_checks_passed']}")
    print(f"  accounting         {result['accounting']['clean_cases']} clean / "
          f"{result['accounting']['crash_cases']} crash / "
          f"{result['accounting']['total_cases']} total")
    print(f"  output             {output}")
    return 0 if result["all_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
