"""Tests for the armed Spider regression gate.

A gate that passes on good input proves nothing — one hardcoded `return 0` scores
100% on that test. The weight is carried by the cases where it must FAIL: each
armed metric regressing past its own threshold, and each always-fail condition.

Also tested: movement *within* a threshold must pass. A gate that fires on noise
gets disabled by whoever it wakes at 2am, and then it protects nothing.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.check_spider_gate import (  # noqa: E402
    GateError,
    check_integrity,
    check_metrics,
)

POLICY_PATH = REPO_ROOT / "metrics" / "spider_gate_policy.json"
BASELINE_PATH = REPO_ROOT / "metrics" / "spider_baseline_metrics.json"
CURRENT_PATH = REPO_ROOT / "metrics" / "spider_current_metrics.json"


@pytest.fixture
def policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def baseline() -> dict:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def current(baseline: dict) -> dict:
    return copy.deepcopy(baseline)


# --------------------------------------------------------------- happy path


def test_committed_metrics_pass_the_gate():
    """The committed baseline/current pair must pass, or CI is red on main."""
    result = subprocess.run(
        [sys.executable, "-m", "scripts.check_spider_gate"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "GATE PASSED" in result.stdout


def test_identical_metrics_produce_no_failures(policy, baseline, current):
    failures, report = check_metrics(baseline, current, policy)
    assert failures == []
    assert any("test_suite_task_success" in line for line in report)


# ------------------------------------------------- armed metrics must fail


@pytest.mark.parametrize(
    "metric,direction,threshold",
    [
        ("test_suite_task_success", "decrease", 0.027079),
        ("mean_model_turns_per_success", "increase", 0.055692),
        ("tool_validity_rate", "decrease", 0.001912),
        ("estimated_cost_per_success", "increase", 0.000080),
    ],
)
def test_each_armed_metric_fails_when_it_regresses(
    policy, baseline, current, metric, direction, threshold
):
    """Every armed metric must independently be able to fail the gate."""
    move = threshold * 1.5
    current["gate_metrics"][metric] += -move if direction == "decrease" else move

    failures, _ = check_metrics(baseline, current, policy)
    assert len(failures) == 1, failures
    assert metric in failures[0]


@pytest.mark.parametrize(
    "metric,direction,threshold",
    [
        ("test_suite_task_success", "decrease", 0.027079),
        ("mean_model_turns_per_success", "increase", 0.055692),
        ("tool_validity_rate", "decrease", 0.001912),
        ("estimated_cost_per_success", "increase", 0.000080),
    ],
)
def test_movement_inside_the_threshold_passes(
    policy, baseline, current, metric, direction, threshold
):
    """Noise must not fire the gate. The threshold IS the noise envelope."""
    move = threshold * 0.5
    current["gate_metrics"][metric] += -move if direction == "decrease" else move

    failures, _ = check_metrics(baseline, current, policy)
    assert failures == []


def test_improvement_never_fails(policy, baseline, current):
    """Moving in the good direction, however far, is not a regression."""
    current["gate_metrics"]["test_suite_task_success"] += 0.20
    current["gate_metrics"]["estimated_cost_per_success"] = 0.0
    current["gate_metrics"]["tool_validity_rate"] = 1.0

    failures, _ = check_metrics(baseline, current, policy)
    assert failures == []


def test_unarmed_metric_is_reported_but_never_fails(policy, baseline, current):
    """pass^4 needs k repeats per side; a single CI run cannot produce it."""
    _, report = check_metrics(baseline, current, policy)
    assert any("consistency_pass_pow_4" in line and "monitor" in line for line in report)


# ----------------------------------------- always-fail conditions must fail


def test_wrong_episode_count_fails(policy, current):
    current["integrity"]["episodes_measured"] = 1000
    failures = check_integrity(current, policy)
    assert any("1000" in f and "1034" in f for f in failures)


@pytest.mark.parametrize(
    "field",
    [
        "infrastructure_terminations",
        "evaluator_infrastructure_failures",
        "gold_query_failures",
        "missing_trajectories",
    ],
)
def test_any_infrastructure_failure_fails(policy, current, field):
    """Infrastructure correctness is not tunable — one is enough."""
    current["integrity"][field] = 1
    failures = check_integrity(current, policy)
    assert len(failures) == 1, failures


def test_duplicate_task_ids_fail(policy, current):
    current["integrity"]["duplicate_task_ids"] = {"task_7": 2}
    failures = check_integrity(current, policy)
    assert any("duplicate" in f for f in failures)


def test_trace_mismatch_fails(policy, current):
    """The observability side-channel must corroborate the quality numbers."""
    current["integrity"]["trace_matches_trajectory"] = False
    failures = check_integrity(current, policy)
    assert any("matches_trajectory" in f for f in failures)


def test_missing_integrity_block_is_an_error_not_a_pass(policy, current):
    del current["integrity"]
    with pytest.raises(GateError):
        check_integrity(current, policy)


# ------------------------------------------------------- refuse to guess


def test_armed_metric_absent_from_current_is_an_error(policy, baseline, current):
    """A metric that cannot be compared must not be silently skipped."""
    del current["gate_metrics"]["tool_validity_rate"]
    with pytest.raises(GateError):
        check_metrics(baseline, current, policy)


def test_gate_fails_closed_on_missing_file():
    result = subprocess.run(
        [sys.executable, "-m", "scripts.check_spider_gate",
         "--current", "metrics/does_not_exist.json"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "not a pass" in result.stdout


def test_baseline_metrics_carry_their_provenance(baseline):
    """A baseline whose origin cannot be traced is a number someone typed in."""
    assert baseline["run_id"]
    assert baseline["provenance"]["test_suite_rescore_artifact"]
    assert "no model call" in baseline["provenance"]["scored_from"]
    assert baseline["integrity"]["trace_matches_trajectory"] is True
