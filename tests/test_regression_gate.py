import json
from pathlib import Path

from scripts.compare_regression_metrics import (
    compare_metrics,
    load_metrics,
    main,
)


BASELINE = {
    "eval_score": 0.8,
    "latency_ms": 1000.0,
    "cost_usd": 1.0,
}


def fixture_path(name: str) -> Path:
    directory = Path("runs/test_regression_gate")
    directory.mkdir(parents=True, exist_ok=True)
    return directory / name


def write_metrics(path: Path, metrics: dict) -> None:
    path.write_text(json.dumps(metrics), encoding="utf-8")


def test_regression_gate_passes_when_metrics_are_within_thresholds():
    current = {
        "eval_score": 0.79,
        "latency_ms": 1100.0,
        "cost_usd": 1.1,
    }

    result = compare_metrics(BASELINE, current)

    assert result.passed is True
    assert result.failures == []


def test_regression_gate_fails_for_fake_score_regression():
    current = {
        "eval_score": 0.72,
        "latency_ms": 1000.0,
        "cost_usd": 1.0,
    }

    result = compare_metrics(BASELINE, current)

    assert result.passed is False
    assert result.failures[0].metric == "eval_score"
    assert result.failures[0].regression > 0.05


def test_regression_gate_fails_for_fake_latency_regression():
    current = {
        "eval_score": 0.8,
        "latency_ms": 1200.0,
        "cost_usd": 1.0,
    }

    result = compare_metrics(BASELINE, current)

    assert result.passed is False
    assert result.failures[0].metric == "latency_ms"
    assert result.failures[0].regression > 0.15


def test_regression_gate_fails_for_fake_cost_regression():
    current = {
        "eval_score": 0.8,
        "latency_ms": 1000.0,
        "cost_usd": 1.2,
    }

    result = compare_metrics(BASELINE, current)

    assert result.passed is False
    assert result.failures[0].metric == "cost_usd"
    assert result.failures[0].regression > 0.15


def test_regression_gate_cli_passes_with_fixture_files():
    baseline_path = fixture_path("passing_baseline.json")
    current_path = fixture_path("passing_current.json")
    write_metrics(baseline_path, BASELINE)
    write_metrics(
        current_path,
        {
            "eval_score": 0.79,
            "latency_ms": 1100.0,
            "cost_usd": 1.1,
        },
    )

    exit_code = main(
        [
            "--baseline",
            str(baseline_path),
            "--current",
            str(current_path),
        ]
    )

    assert exit_code == 0


def test_regression_gate_cli_fails_when_fake_regression_is_injected():
    baseline_path = fixture_path("failing_baseline.json")
    current_path = fixture_path("failing_current.json")
    write_metrics(baseline_path, BASELINE)
    write_metrics(
        current_path,
        {
            "eval_score": 0.7,
            "latency_ms": 1300.0,
            "cost_usd": 1.4,
        },
    )

    exit_code = main(
        [
            "--baseline",
            str(baseline_path),
            "--current",
            str(current_path),
        ]
    )

    assert exit_code == 1


def test_load_metrics_rejects_missing_required_metric():
    path = fixture_path("missing_required_metric.json")
    write_metrics(path, {"eval_score": 0.8, "latency_ms": 1000.0})

    exit_code = main(["--baseline", str(path), "--current", str(path)])

    assert exit_code == 2


def test_committed_current_metrics_pass_against_committed_baseline():
    baseline = load_metrics(Path("metrics/baseline_metrics.json"))
    current = load_metrics(Path("metrics/current_metrics.json"))

    assert compare_metrics(baseline, current).passed is True
