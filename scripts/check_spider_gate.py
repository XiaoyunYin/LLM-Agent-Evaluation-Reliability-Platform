"""The armed Spider regression gate. Runs in CI; exits non-zero on regression.

Thresholds are not chosen here. They are read from `metrics/spider_gate_policy.json`,
where each one was derived as `max(2 x observed_spread_across_repeats,
minimum_detectable_change)` from four same-commit repeats — the measured
noise envelope, not a judgement call. The superseded policy (">5% eval score")
was ~3.7x wider than the noise it was meant to sit above, so it would have passed
real regressions silently.

Two classes of check, and the difference is deliberate:

**Armed metrics** fail when the metric moves further than its threshold in the bad
direction. Movement *within* the threshold is noise and is reported, not failed.

**Always-fail conditions** are not tunable. Infrastructure correctness is not a
quality metric you trade off — any non-zero value means the run's quality numbers
describe something other than what they claim, so no threshold applies.

Metrics marked `armed: false` in the policy are reported and never fail CI.
`consistency_pass_pow_4` is the clearest case: it needs k repeats per side, and a
single CI run cannot produce it, so it is a release-gate candidate rather than a
per-commit gate.

    python -m scripts.check_spider_gate \
        --policy metrics/spider_gate_policy.json \
        --baseline metrics/spider_baseline_metrics.json \
        --current metrics/spider_current_metrics.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]


class GateError(Exception):
    """Raised when the gate cannot be evaluated at all, as distinct from failing."""


def load(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise GateError(f"missing required file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise GateError(f"{path} is not valid JSON: {error}") from error


def check_integrity(current: dict[str, Any], policy: dict[str, Any]) -> list[str]:
    """Always-fail conditions. No thresholds, by design."""
    integrity = current.get("integrity")
    if integrity is None:
        raise GateError("current metrics carry no `integrity` block")

    failures: list[str] = []
    expected = integrity.get("expected_episodes")
    measured = integrity.get("episodes_measured")
    if measured != expected:
        failures.append(
            f"episodes measured {measured} != {expected} expected — the run does "
            "not cover the benchmark, so its rates have a different denominator"
        )
    for field, label in (
        ("infrastructure_terminations", "RATE_LIMITED / MODEL_ERROR / TOOL_ERROR episodes"),
        ("evaluator_infrastructure_failures", "evaluator infrastructure failures"),
        ("gold_query_failures", "gold query failures"),
        ("missing_trajectories", "missing trajectories"),
    ):
        value = integrity.get(field, 0)
        if value:
            failures.append(f"{label}: {value} (must be 0)")
    duplicates = integrity.get("duplicate_task_ids") or {}
    if duplicates:
        failures.append(
            f"duplicate task ids: {len(duplicates)} task(s) appear more than once — "
            "the run is contaminated and must be quarantined, not scored"
        )
    if not integrity.get("trace_matches_trajectory", False):
        failures.append(
            "trace_check.matches_trajectory is false — the persisted trajectory and "
            "the emitted spans disagree, so the observability side-channel cannot "
            "corroborate the quality numbers"
        )
    return failures


def check_metrics(
    baseline: dict[str, Any], current: dict[str, Any], policy: dict[str, Any]
) -> tuple[list[str], list[str]]:
    """Compare each armed metric against its policy threshold."""
    specs = policy["gate"]["metrics"]
    base_values = baseline.get("gate_metrics", {})
    curr_values = current.get("gate_metrics", {})

    failures: list[str] = []
    report: list[str] = []

    for name, spec in specs.items():
        if not spec.get("armed"):
            report.append(f"  [monitor] {name}: not armed — {spec.get('why_not_armed', '')}")
            continue
        threshold = spec.get("threshold")
        if threshold is None:
            raise GateError(f"metric {name} is armed but has no threshold")
        if name not in base_values or name not in curr_values:
            raise GateError(
                f"metric {name} is armed but missing from "
                f"{'baseline' if name not in base_values else 'current'} metrics"
            )

        base = base_values[name]
        curr = curr_values[name]
        delta = curr - base
        # "Bad" is direction-dependent, so normalise to a positive regression size.
        regression = -delta if spec["direction"] == "decrease_is_bad" else delta
        verdict = "FAIL" if regression > threshold else "ok"
        line = (
            f"  [{verdict:>4}] {name}: {base:.6f} -> {curr:.6f} "
            f"(moved {delta:+.6f}, threshold {threshold:.6f} "
            f"{spec['direction']})"
        )
        report.append(line)
        if verdict == "FAIL":
            failures.append(
                f"{name} regressed by {regression:.6f}, over the {threshold:.6f} "
                f"threshold derived from a measured spread of "
                f"{spec.get('observed_spread')}"
            )
    return failures, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", default="metrics/spider_gate_policy.json")
    parser.add_argument("--baseline", default="metrics/spider_baseline_metrics.json")
    parser.add_argument("--current", default="metrics/spider_current_metrics.json")
    args = parser.parse_args()

    try:
        policy = load(REPO_ROOT / args.policy)
        baseline = load(REPO_ROOT / args.baseline)
        current = load(REPO_ROOT / args.current)

        if policy.get("status") != "ARMED":
            print(f"gate status is {policy.get('status')!r}, not ARMED — nothing enforced")
            return 0

        integrity_failures = check_integrity(current, policy)
        metric_failures, report = check_metrics(baseline, current, policy)
    except GateError as error:
        print(f"GATE ERROR: {error}")
        print("The gate could not be evaluated. This is a failure, not a pass.")
        return 2

    print(f"Spider regression gate — policy {policy['policy_version']}")
    print(f"  baseline run {baseline.get('run_id')}")
    print(f"  current  run {current.get('run_id')}\n")
    for line in report:
        print(line)

    if integrity_failures:
        print("\nALWAYS-FAIL CONDITIONS TRIPPED:")
        for failure in integrity_failures:
            print(f"  - {failure}")

    failures = integrity_failures + metric_failures
    if failures:
        print(f"\nGATE FAILED ({len(failures)} condition(s))")
        return 1
    print("\nGATE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
