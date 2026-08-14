"""Extract the CI gate's input metrics from a completed benchmark run.

Produces the small, reviewable JSON that `check_spider_gate.py` compares. Keeping
extraction separate from comparison matters: the gate must be runnable in CI
without the run artifacts present, and the extracted file is what gets committed
and diffed in a pull request.

Every metric is recomputed from `episodes.jsonl` and the test-suite rescore rather
than copied from `p0_metrics.json`, because a gate that reads the same summary the
pipeline wrote cannot catch the pipeline miscomputing it.

    python -m scripts.extract_gate_metrics --run-id spider_p2__treat_2 \
        --output metrics/spider_baseline_metrics.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

RUN_ROOT = REPO_ROOT / "runs" / "spider_benchmark"
EXPECTED_EPISODES = 1034

# Terminations that mean the harness failed, not the agent. Any of these
# invalidates the run's quality numbers regardless of how good they look.
INFRASTRUCTURE_TERMINATIONS = ("RATE_LIMITED", "MODEL_ERROR", "TOOL_ERROR")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def live_trace_check(run_id: str, elasticsearch_url: str, index: str) -> dict[str, Any]:
    """Recompute trace reconciliation now, rather than trusting the run's own record.

    The value stored in `p0_metrics.json` was computed moments after the run
    finished, when Elasticsearch had not finished ingesting. Several runs recorded
    `matches_trajectory: false` purely from that lag and reconcile exactly when
    re-queried. Reading the stored value would therefore reject good runs.

    Recomputing also keeps a frozen artifact frozen: the stale verdict stays in the
    run directory as the historical record, and the fresh one is stamped with the
    time it was taken.
    """
    from scripts.report_spider_metrics import build_report, count_run_spans

    check = count_run_spans(run_id, elasticsearch_url, index)
    report = build_report(run_id, RUN_ROOT, check)
    check = report.get("trace_check", {})
    if not check.get("available"):
        raise ValueError(
            f"trace check unavailable for {run_id}: {check.get('error', 'unknown')}. "
            "The gate treats trace reconciliation as an always-fail condition, so a "
            "baseline cannot be extracted without it."
        )
    return {
        "matches_trajectory": bool(check.get("matches_trajectory", False)),
        "span_documents": check.get("span_documents"),
        "reconciliation": check.get("reconciliation", {}),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def extract(run_id: str, elasticsearch_url: str, index: str) -> dict[str, Any]:
    run_dir = RUN_ROOT / run_id
    trace_verdict = live_trace_check(run_id, elasticsearch_url, index)
    episodes = _read_jsonl(run_dir / "episodes.jsonl")

    terminations = Counter(e["termination_reason"] for e in episodes)
    successes = [e for e in episodes if e["termination_reason"] == "SUCCESS"]

    tool_calls = sum(e.get("tool_steps", 0) for e in episodes)

    # Refuse to default a missing counter to zero. `bad_argument_tool_calls` was
    # added in P1, so P0-era runs do not carry it - and `.get(field, 0)` silently
    # turned "never recorded" into "zero malformed calls", producing a
    # tool_validity_rate of exactly 1.0 for a run that never measured it. That is
    # the same silent-failure class this project keeps finding: absent data
    # rendered as a plausible value. A metric that cannot be computed is an error,
    # never a default.
    missing = [e["task_id"] for e in episodes if "bad_argument_tool_calls" not in e]
    if missing:
        raise ValueError(
            f"{len(missing)} of {len(episodes)} episodes in {run_id} do not record "
            "`bad_argument_tool_calls`, so tool_validity_rate cannot be computed. "
            "This run predates the counter and cannot serve as a gate baseline."
        )
    bad_calls = sum(e["bad_argument_tool_calls"] for e in episodes)

    # Test-suite accuracy comes from the offline rescore: the same persisted SQL
    # scored against the distilled instances, no model re-run.
    rescore_path = run_dir / "rescore__test_suite.json"
    rescore = json.loads(rescore_path.read_text(encoding="utf-8"))
    test_suite_accuracy = rescore["result"]["accuracy"]

    # p0_metrics is consulted ONLY for evaluator-side facts the episode rows cannot
    # express. The trace verdict is deliberately NOT taken from it.
    metrics_path = run_dir / "p0_metrics.json"
    published = json.loads(metrics_path.read_text(encoding="utf-8"))
    infrastructure = published.get("infrastructure_correctness", {})

    task_ids = [e["task_id"] for e in episodes]
    duplicates = {t: n for t, n in Counter(task_ids).items() if n > 1}

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "policy_version": "p1_armed_v1",
        "gate_metrics": {
            "test_suite_task_success": test_suite_accuracy,
            "mean_model_turns_per_success": (
                sum(e.get("model_steps", 0) for e in successes) / len(successes)
                if successes else 0.0
            ),
            "tool_validity_rate": (
                1.0 - (bad_calls / tool_calls) if tool_calls else 1.0
            ),
            "estimated_cost_per_success": (
                sum(e.get("estimated_cost", 0.0) for e in episodes) / len(successes)
                if successes else 0.0
            ),
        },
        "monitor_metrics": {
            "single_database_execution_accuracy": len(successes) / len(episodes),
            "sql_execution_error_rate": (
                published.get("tool_behavior", {}).get("sql_execution_error_rate")
            ),
            "termination_reason_distribution": dict(sorted(terminations.items())),
        },
        "integrity": {
            "episodes_measured": len(episodes),
            "expected_episodes": EXPECTED_EPISODES,
            "infrastructure_terminations": sum(
                terminations.get(reason, 0) for reason in INFRASTRUCTURE_TERMINATIONS
            ),
            "evaluator_infrastructure_failures": infrastructure.get(
                "evaluator_infrastructure_failures", 0
            ),
            "gold_query_failures": infrastructure.get("gold_query_failures", 0),
            "missing_trajectories": infrastructure.get("missing_trajectories", 0),
            "duplicate_task_ids": duplicates,
            "trace_matches_trajectory": trace_verdict["matches_trajectory"],
            "trace_checked_at": trace_verdict["checked_at"],
            "trace_span_documents": trace_verdict["span_documents"],
        },
        "provenance": {
            "tool_calls": tool_calls,
            "malformed_tool_calls": bad_calls,
            "successes": len(successes),
            "test_suite_rescore_artifact": str(
                rescore_path.relative_to(REPO_ROOT)
            ).replace("\\", "/"),
            "scored_from": rescore.get("scored_from", ""),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--elasticsearch-url", default="http://localhost:9200")
    parser.add_argument("--trace-index", default="otel-traces")
    parser.add_argument(
        "--note", default="", help="recorded verbatim in the output for reviewers"
    )
    args = parser.parse_args()

    payload = extract(args.run_id, args.elasticsearch_url, args.trace_index)
    if args.note:
        payload["note"] = args.note

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(f"{args.run_id} -> {output}")
    for name, value in payload["gate_metrics"].items():
        print(f"  {name:<32} {value}")
    integrity = payload["integrity"]
    print(f"  episodes {integrity['episodes_measured']}, "
          f"infra terminations {integrity['infrastructure_terminations']}, "
          f"duplicates {len(integrity['duplicate_task_ids'])}")
    print(f"  trace reconciliation {integrity['trace_matches_trajectory']} "
          f"({integrity['trace_span_documents']} spans, re-queried now)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
