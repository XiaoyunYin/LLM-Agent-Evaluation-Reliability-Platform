import json
from pathlib import Path

import pytest

from scripts.run_p4a_matrix import enumerate_cases, run_matrix, selected_entries, write_quarantine


def test_p4a_matrix_enumerates_clean_and_crash_cases_for_selected_task():
    entries = selected_entries({"SUP-policy-001"})
    cases = [case for case, _entry in enumerate_cases(entries)]

    assert len(cases) == 16
    assert sum(1 for case in cases if case.crash_window is None) == 1
    assert sum(1 for case in cases if case.tool_name == "update_ticket") == 5
    assert sum(1 for case in cases if case.tool_name == "assign_ticket") == 5
    assert sum(1 for case in cases if case.tool_name == "add_comment") == 5


def test_p4a_matrix_writes_artifact_for_selected_task(tmp_path: Path):
    report = run_matrix(
        run_id="unit",
        task_ids={"SUP-policy-001"},
        output_root=tmp_path,
        lease_ttl=0.01,
    )

    artifact = tmp_path / "unit" / "p4a_matrix.json"
    assert artifact.exists()
    saved = json.loads(artifact.read_text(encoding="utf-8"))
    assert saved["all_passed"] is True
    assert saved["model_calls_made"] == 0
    assert saved["summary"]["cases"] == 16
    assert saved["summary"]["passed_cases"] == 16
    assert saved["summary"]["acceptance_totals"] == {
        "duplicate_side_effects": 0,
        "lost_required_effects": 0,
        "incorrect_final_states": 0,
        "stale_fenced_effects_accepted": 0,
        "orphan_effect_records": 0,
        "invariant_violations": 0,
    }
    assert not (tmp_path / "unit" / "QUARANTINE.json").exists()

    crash_case = next(case for case in saved["cases"] if case["crash_window"])
    assert crash_case["crash_observed"] is True
    assert crash_case["latency"]["detection_latency_ms"] == 10.0
    assert crash_case["verification"]["passed"] is True


def test_p4a_matrix_writes_quarantine_tombstone_for_failed_report(tmp_path: Path):
    run_dir = tmp_path / "bad"
    run_dir.mkdir()
    report = {
        "run_id": "bad",
        "cases": [
            {
                "case_id": "case-1",
                "task_id": "SUP-policy-001",
                "crash_window": "after_intent_before_effect",
                "step_index": 1,
                "error": "ProtocolViolation: injected",
                "acceptance_counts": {"invariant_violations": 1},
                "verification": {"passed": False},
                "passed": False,
            }
        ],
    }

    write_quarantine(run_dir, report)

    tombstone = json.loads((run_dir / "QUARANTINE.json").read_text(encoding="utf-8"))
    assert tombstone["contamination_reason"] == "p4a_protocol_matrix_failure"
    assert tombstone["failed_cases"][0]["case_id"] == "case-1"


def test_p4a_matrix_rejects_unknown_task_id():
    with pytest.raises(ValueError):
        selected_entries({"SUP-no-such-task"})
