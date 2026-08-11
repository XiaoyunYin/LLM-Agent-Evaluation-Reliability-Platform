import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


DEFAULT_SCORE_REGRESSION_THRESHOLD = 0.05
DEFAULT_LATENCY_REGRESSION_THRESHOLD = 0.15
DEFAULT_COST_REGRESSION_THRESHOLD = 0.15
REQUIRED_METRICS = ("eval_score", "latency_ms", "cost_usd")


class RegressionGateError(Exception):
    pass


@dataclass(frozen=True)
class MetricComparison:
    metric: str
    baseline: float
    current: float
    regression: float
    threshold: float
    passed: bool
    direction: str


@dataclass(frozen=True)
class RegressionGateResult:
    passed: bool
    comparisons: list[MetricComparison]

    @property
    def failures(self) -> list[MetricComparison]:
        return [comparison for comparison in self.comparisons if not comparison.passed]


def load_metrics(path: Path) -> dict[str, float]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise RegressionGateError(f"Metrics file not found: {path}") from error
    except json.JSONDecodeError as error:
        raise RegressionGateError(f"Metrics file is not valid JSON: {path}") from error

    metrics: dict[str, float] = {}
    for key in REQUIRED_METRICS:
        value = raw.get(key)
        if not isinstance(value, int | float):
            raise RegressionGateError(f"Missing numeric metric '{key}' in {path}")
        metrics[key] = float(value)

    validate_positive(metrics, path)
    return metrics


def validate_positive(metrics: dict[str, float], path: Path) -> None:
    if not 0.0 <= metrics["eval_score"] <= 1.0:
        raise RegressionGateError(f"eval_score must be between 0 and 1 in {path}")
    if metrics["latency_ms"] <= 0:
        raise RegressionGateError(f"latency_ms must be positive in {path}")
    if metrics["cost_usd"] <= 0:
        raise RegressionGateError(f"cost_usd must be positive in {path}")


def compare_metrics(
    baseline: dict[str, float],
    current: dict[str, float],
    score_threshold: float = DEFAULT_SCORE_REGRESSION_THRESHOLD,
    latency_threshold: float = DEFAULT_LATENCY_REGRESSION_THRESHOLD,
    cost_threshold: float = DEFAULT_COST_REGRESSION_THRESHOLD,
) -> RegressionGateResult:
    comparisons = [
        compare_higher_is_better(
            metric="eval_score",
            baseline=baseline["eval_score"],
            current=current["eval_score"],
            threshold=score_threshold,
        ),
        compare_lower_is_better(
            metric="latency_ms",
            baseline=baseline["latency_ms"],
            current=current["latency_ms"],
            threshold=latency_threshold,
        ),
        compare_lower_is_better(
            metric="cost_usd",
            baseline=baseline["cost_usd"],
            current=current["cost_usd"],
            threshold=cost_threshold,
        ),
    ]

    return RegressionGateResult(
        passed=all(comparison.passed for comparison in comparisons),
        comparisons=comparisons,
    )


def compare_higher_is_better(
    metric: str,
    baseline: float,
    current: float,
    threshold: float,
) -> MetricComparison:
    regression = (baseline - current) / baseline
    return MetricComparison(
        metric=metric,
        baseline=baseline,
        current=current,
        regression=regression,
        threshold=threshold,
        passed=regression <= threshold,
        direction="higher_is_better",
    )


def compare_lower_is_better(
    metric: str,
    baseline: float,
    current: float,
    threshold: float,
) -> MetricComparison:
    regression = (current - baseline) / baseline
    return MetricComparison(
        metric=metric,
        baseline=baseline,
        current=current,
        regression=regression,
        threshold=threshold,
        passed=regression <= threshold,
        direction="lower_is_better",
    )


def render_result(result: RegressionGateResult) -> str:
    lines = ["regression_gate"]
    lines.append(f"status: {'passed' if result.passed else 'failed'}")

    for comparison in result.comparisons:
        lines.append(
            "metric={metric} baseline={baseline:.6g} current={current:.6g} "
            "regression={regression:.2%} threshold={threshold:.2%} "
            "direction={direction} status={status}".format(
                metric=comparison.metric,
                baseline=comparison.baseline,
                current=comparison.current,
                regression=comparison.regression,
                threshold=comparison.threshold,
                direction=comparison.direction,
                status="passed" if comparison.passed else "failed",
            )
        )

    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--baseline",
        type=Path,
        default=Path("metrics/baseline_metrics.json"),
    )
    parser.add_argument(
        "--current",
        type=Path,
        default=Path("metrics/current_metrics.json"),
    )
    parser.add_argument(
        "--score-threshold",
        type=float,
        default=DEFAULT_SCORE_REGRESSION_THRESHOLD,
    )
    parser.add_argument(
        "--latency-threshold",
        type=float,
        default=DEFAULT_LATENCY_REGRESSION_THRESHOLD,
    )
    parser.add_argument(
        "--cost-threshold",
        type=float,
        default=DEFAULT_COST_REGRESSION_THRESHOLD,
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        baseline = load_metrics(args.baseline)
        current = load_metrics(args.current)
        result = compare_metrics(
            baseline=baseline,
            current=current,
            score_threshold=args.score_threshold,
            latency_threshold=args.latency_threshold,
            cost_threshold=args.cost_threshold,
        )
    except RegressionGateError as error:
        print(f"regression_gate\nstatus: invalid\nerror: {error}", file=sys.stderr)
        return 2

    output = render_result(result)
    if result.passed:
        print(output)
        return 0

    print(output, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
