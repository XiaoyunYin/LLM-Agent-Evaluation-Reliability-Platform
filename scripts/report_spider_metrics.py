"""Compute the P0 metrics from a persisted Spider benchmark run (plan, Step 16).

Every number here is derived from `episodes.jsonl` and `steps.jsonl`. Nothing is
passed in, nothing is assumed, and the script refuses to report a run it cannot
fully account for - if episodes are missing or duplicated, that is stated instead
of being averaged away.

Three deliberate separations:

- **Agent failures vs infrastructure failures.** `MODEL_ERROR` and `TOOL_ERROR`
  mean this platform broke, not that the model was wrong. They are reported in
  their own block and excluded from nothing, so a run with infrastructure
  failures cannot be read as a clean quality measurement.
- **`SQL_ERROR` vs `VERIFICATION_FAILED`.** Query does not run, versus runs and
  returns the wrong answer. Different fixes.
- **Estimated cost vs billed cost.** Cost is computed from published list price
  and labelled as an estimate everywhere it appears.

Usage:
    python scripts/report_spider_metrics.py --run-id spider_full__...
    python scripts/report_spider_metrics.py --run-id ... --check-traces
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

from backend.app.spider.trajectory import (  # noqa: E402
    DEFAULT_RUN_ROOT,
    INFRASTRUCTURE_TERMINATIONS,
    TerminationReason,
    TrajectoryStore,
)

DEFAULT_ELASTICSEARCH_URL = "http://127.0.0.1:9200"
DEFAULT_TRACE_INDEX = "otel-traces"


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def count_run_spans(run_id: str, elasticsearch_url: str, index: str) -> dict[str, Any]:
    """Count spans in Elasticsearch belonging to this run.

    Reported as `unavailable` rather than `0` when Elasticsearch cannot be
    reached. Those are different facts, and conflating them would let a missing
    collector look like missing instrumentation.
    """
    import requests

    base = elasticsearch_url.rstrip("/")
    query = {
        "size": 0,
        # Without this, Elasticsearch stops counting at 10,000 and reports exactly
        # 10,000 as though it were the total. A full run emits more than that, so
        # the default would silently under-report the span count.
        "track_total_hits": True,
        "query": {
            "bool": {
                "should": [
                    {"term": {f"attributes.run.id{suffix}": run_id}}
                    for suffix in ("", ".keyword")
                ],
                "minimum_should_match": 1,
            }
        },
        "aggs": {"span_names": {"terms": {"field": "name.keyword", "size": 20}}},
    }
    try:
        response = requests.post(f"{base}/{index}/_search", json=query, timeout=15)
        response.raise_for_status()
        body = response.json()
    except Exception as error:  # noqa: BLE001
        return {"available": False, "error": f"{type(error).__name__}: {error}"}

    buckets = body.get("aggregations", {}).get("span_names", {}).get("buckets", [])
    return {
        "available": True,
        "span_documents": body.get("hits", {}).get("total", {}).get("value", 0),
        "by_span_name": {b["key"]: b["doc_count"] for b in buckets},
    }


def build_report(
    run_id: str,
    root: Path,
    trace_check: dict[str, Any] | None,
) -> dict[str, Any]:
    store = TrajectoryStore(run_id, root)
    if not store.episodes_path.exists():
        raise SystemExit(f"No episodes at {store.episodes_path}")

    configuration = (
        json.loads(store.config_path.read_text(encoding="utf-8"))
        if store.config_path.exists()
        else {}
    )
    episodes = list(store.iter_episodes())
    steps = list(store.iter_steps())

    duplicates = store.duplicate_task_ids()
    selected = configuration.get("selected_task_ids") or []
    measured_ids = {episode["task_id"] for episode in episodes}
    missing_trajectories = sorted(set(selected) - measured_ids) if selected else []

    total = len(episodes)
    terminations: dict[str, int] = {}
    for episode in episodes:
        reason = episode["termination_reason"]
        terminations[reason] = terminations.get(reason, 0) + 1

    successes = [
        e for e in episodes if e["termination_reason"] == TerminationReason.SUCCESS.value
    ]
    infrastructure = [
        e
        for e in episodes
        if e["termination_reason"] in {r.value for r in INFRASTRUCTURE_TERMINATIONS}
    ]

    # Verification outcomes recorded by the evaluator, independent of termination.
    evaluator_errors = sum(
        1
        for e in episodes
        if (e.get("verification_result") or {}).get("outcome") == "evaluator_error"
    )
    gold_errors = sum(
        1
        for e in episodes
        if (e.get("verification_result") or {}).get("outcome") == "gold_error"
    )

    success_steps = [float(e["total_steps"]) for e in successes]
    all_steps = [float(e["total_steps"]) for e in episodes]

    total_sql_executions = sum(e["sql_executions"] for e in episodes)
    total_sql_errors = sum(e["sql_execution_errors"] for e in episodes)

    success_input = [float(e["input_tokens"]) for e in successes]
    success_output = [float(e["output_tokens"]) for e in successes]
    success_cost = [float(e["estimated_cost"]) for e in successes]
    total_cost = sum(float(e["estimated_cost"]) for e in episodes)

    steps_without_trace = sum(1 for step in steps if not step.get("trace_id"))
    episodes_without_trace = sum(1 for e in episodes if not e.get("trace_id"))
    step_records_by_episode: dict[str, int] = {}
    for step in steps:
        step_records_by_episode[step["episode_id"]] = (
            step_records_by_episode.get(step["episode_id"], 0) + 1
        )
    step_count_disagreements = [
        e["episode_id"]
        for e in episodes
        if step_records_by_episode.get(e["episode_id"], 0) != e["total_steps"]
    ]

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "is_mock": bool(configuration.get("is_mock")),
        "stage": configuration.get("stage"),
        "configuration": {
            key: configuration.get(key)
            for key in (
                "dataset",
                "dataset_version",
                "split",
                "model_version",
                "prompt_version",
                "tool_schema_version",
                "adapter_version",
                "agent_version",
                "max_steps",
                "temperature",
                "max_visible_rows",
                "code_commit_sha",
                "code_working_tree_dirty",
                "archive_sha256",
                "valid_task_count",
                "excluded_task_ids",
                "sampled",
                "sample_seed",
                "model_pricing_usd_per_1m",
            )
        },
        "primary": {
            "episodes_measured": total,
            "tasks_selected": len(selected) or total,
            "passed": len(successes),
            "task_success_rate": _ratio(len(successes), total),
        },
        "agent_efficiency": {
            "mean_steps_per_successful_task": _mean(success_steps),
            "median_steps_per_successful_task": _median(success_steps),
            "mean_steps_all_tasks": _mean(all_steps),
            "median_steps_all_tasks": _median(all_steps),
            "mean_model_steps_all_tasks": _mean(
                [float(e["model_steps"]) for e in episodes]
            ),
        },
        "tool_behavior": {
            "sql_executions_total": total_sql_executions,
            "sql_execution_errors_total": total_sql_errors,
            "sql_execution_error_rate": _ratio(total_sql_errors, total_sql_executions),
            "schema_inspections_per_episode": _mean(
                [float(e["schema_inspections"]) for e in episodes]
            ),
            "sql_executions_per_episode": _mean(
                [float(e["sql_executions"]) for e in episodes]
            ),
            "episodes_with_zero_schema_inspections": sum(
                1 for e in episodes if e["schema_inspections"] == 0
            ),
            "episodes_with_zero_sql_executions": sum(
                1 for e in episodes if e["sql_executions"] == 0
            ),
        },
        "economics": {
            "pricing_basis": "published list price, not a billed invoice",
            "mean_input_tokens_per_successful_task": _mean(success_input),
            "mean_output_tokens_per_successful_task": _mean(success_output),
            "mean_estimated_cost_per_successful_task": _mean(success_cost),
            "mean_estimated_cost_per_episode": _ratio(total_cost, total),
            "total_estimated_cost": total_cost,
            "total_input_tokens": sum(e["input_tokens"] for e in episodes),
            "total_output_tokens": sum(e["output_tokens"] for e in episodes),
        },
        "failure_breakdown": {
            "termination_counts": terminations,
            "verification_failures": terminations.get(
                TerminationReason.VERIFICATION_FAILED.value, 0
            ),
            "sql_errors": terminations.get(TerminationReason.SQL_ERROR.value, 0),
            "max_step_terminations": terminations.get(
                TerminationReason.MAX_STEPS.value, 0
            ),
            "model_failures": terminations.get(TerminationReason.MODEL_ERROR.value, 0),
            "tool_failures": terminations.get(TerminationReason.TOOL_ERROR.value, 0),
            "missing_final_sql": terminations.get(
                TerminationReason.NO_FINAL_SQL.value, 0
            ),
        },
        "infrastructure_correctness": {
            "generation_infrastructure_failures": terminations.get(
                TerminationReason.MODEL_ERROR.value, 0
            ),
            "tool_infrastructure_failures": terminations.get(
                TerminationReason.TOOL_ERROR.value, 0
            ),
            "evaluator_infrastructure_failures": evaluator_errors,
            "gold_query_failures": gold_errors,
            "infrastructure_failure_rate": _ratio(len(infrastructure), total),
            "missing_trajectories": len(missing_trajectories),
            "missing_trajectory_task_ids": missing_trajectories[:50],
            "duplicate_task_ids": duplicates,
            "episodes_without_trace_id": episodes_without_trace,
            "steps_without_trace_id": steps_without_trace,
            "step_count_disagreements": len(step_count_disagreements),
            "total_step_records": len(steps),
        },
        "latency": {
            "mean_episode_latency_ms": _mean(
                [float(e["latency_ms"]) for e in episodes]
            ),
            "median_episode_latency_ms": _median(
                [float(e["latency_ms"]) for e in episodes]
            ),
        },
    }

    if trace_check is not None:
        if trace_check.get("available"):
            # "Trace data matches persisted trajectory data" (plan, Step 18) has to
            # be an assertion against countable quantities, not an eyeball check.
            # Every model step and every episode must appear exactly once as a
            # span; a shortfall means spans were dropped, and an excess means
            # something double-emitted.
            by_name = trace_check.get("by_span_name", {})
            expected_model_spans = sum(e["model_steps"] for e in episodes)
            expected_verifier_spans = sum(
                1 for e in episodes if e.get("verification_result") is not None
            )

            # Every tool name that appears in the trajectory must be reconciled,
            # not a chosen subset. An earlier version checked four span types, and
            # the two it skipped were exactly the two with gaps: `inspect_schema`
            # was short 23 spans (rejected arguments returned before the span
            # opened) and `submit_answer` had none at all. Both are fixed in the
            # agent; enumerating from the data means a future gap cannot hide in a
            # span type nobody thought to list.
            tool_call_counts: dict[str, int] = {}
            for step in steps:
                if step["step_type"] == "tool" and step.get("tool_name"):
                    tool_call_counts[step["tool_name"]] = (
                        tool_call_counts.get(step["tool_name"], 0) + 1
                    )

            reconciliation = {
                "agent.episode": {
                    "expected": total,
                    "found": by_name.get("agent.episode", 0),
                },
                "agent.model_step": {
                    "expected": expected_model_spans,
                    "found": by_name.get("agent.model_step", 0),
                },
                "verifier.execution": {
                    "expected": expected_verifier_spans,
                    "found": by_name.get("verifier.execution", 0),
                },
                "sqlite.query": {
                    "expected": total_sql_executions,
                    "found": by_name.get("sqlite.query", 0),
                },
            }
            for tool_name, count in sorted(tool_call_counts.items()):
                reconciliation[f"tool.{tool_name}"] = {
                    "expected": count,
                    "found": by_name.get(f"tool.{tool_name}", 0),
                }

            trace_check["reconciliation"] = reconciliation
            trace_check["matches_trajectory"] = all(
                entry["expected"] == entry["found"]
                for entry in reconciliation.values()
            )
            # Spans legitimately outnumber trajectory records: eval.run,
            # agent.episode, sqlite.query, and verifier.execution have no step row.
            trace_check["span_accounting"] = {
                "trajectory_step_records": len(steps),
                "spans_without_a_step_record": {
                    "eval.run": by_name.get("eval.run", 0),
                    "agent.episode": by_name.get("agent.episode", 0),
                    "sqlite.query": by_name.get("sqlite.query", 0),
                    "verifier.execution": by_name.get("verifier.execution", 0),
                },
                "note": (
                    "eval.run and agent.episode are run/episode scopes; "
                    "sqlite.query is nested inside tool.execute_sql; "
                    "verifier.execution runs after the graph finishes. None of "
                    "these are agent steps, so none appear in steps.jsonl."
                ),
            }
        report["trace_check"] = trace_check

    # A single flag summarising whether this run is reportable at all.
    report["run_is_clean"] = (
        not duplicates
        and not missing_trajectories
        and not step_count_disagreements
        and episodes_without_trace == 0
        and len(infrastructure) == 0
        and evaluator_errors == 0
        and gold_errors == 0
    )
    return report


def print_report(report: dict[str, Any]) -> None:
    primary = report["primary"]
    print(f"Run {report['run_id']}  (stage={report['stage']})")
    if report["is_mock"]:
        print("  *** MOCK REHEARSAL - NOT A MEASURED RESULT ***")
    config = report["configuration"]
    print(f"  dataset   {config['dataset_version']}")
    print(f"  model     {config['model_version']}  prompt={config['prompt_version']}  "
          f"tools={config['tool_schema_version']}  max_steps={config['max_steps']}")
    print(f"  commit    {str(config['code_commit_sha'])[:12]}"
          f"{'  (dirty working tree)' if config['code_working_tree_dirty'] else ''}")
    print()

    rate = primary["task_success_rate"]
    print("PRIMARY")
    print(f"  task success (execution accuracy)   {primary['passed']:,}/"
          f"{primary['episodes_measured']:,} = "
          f"{rate:.4f} ({rate:.2%})" if rate is not None else "  no episodes")
    print()

    efficiency = report["agent_efficiency"]
    print("AGENT EFFICIENCY")
    for label, key in (
        ("mean steps / successful task", "mean_steps_per_successful_task"),
        ("median steps / successful task", "median_steps_per_successful_task"),
        ("mean steps / all tasks", "mean_steps_all_tasks"),
        ("mean model steps / all tasks", "mean_model_steps_all_tasks"),
    ):
        value = efficiency[key]
        print(f"  {label:<34} {value:.2f}" if value is not None else f"  {label:<34} n/a")
    print()

    tool = report["tool_behavior"]
    print("TOOL BEHAVIOR")
    error_rate = tool["sql_execution_error_rate"]
    print(f"  sql executions                     {tool['sql_executions_total']:,}")
    print(f"  sql execution errors               {tool['sql_execution_errors_total']:,}")
    print(f"  sql execution-error rate           "
          f"{error_rate:.4f} ({error_rate:.2%})" if error_rate is not None else
          "  sql execution-error rate           n/a")
    print(f"  schema inspections / episode       {tool['schema_inspections_per_episode']:.2f}")
    print(f"  sql executions / episode           {tool['sql_executions_per_episode']:.2f}")
    print(f"  episodes never inspecting schema   {tool['episodes_with_zero_schema_inspections']:,}")
    print(f"  episodes never executing sql       {tool['episodes_with_zero_sql_executions']:,}")
    print()

    economics = report["economics"]
    print("ECONOMICS  (estimated from list price, not a billed invoice)")
    for label, key, fmt in (
        ("input tokens / successful task", "mean_input_tokens_per_successful_task", ",.0f"),
        ("output tokens / successful task", "mean_output_tokens_per_successful_task", ",.0f"),
        ("est. cost / successful task", "mean_estimated_cost_per_successful_task", ".6f"),
        ("est. cost / episode", "mean_estimated_cost_per_episode", ".6f"),
        ("total estimated cost", "total_estimated_cost", ".4f"),
    ):
        value = economics[key]
        print(f"  {label:<34} {value:{fmt}}" if value is not None else f"  {label:<34} n/a")
    print()

    failures = report["failure_breakdown"]
    print("FAILURE BREAKDOWN")
    for reason, count in sorted(
        failures["termination_counts"].items(), key=lambda item: -item[1]
    ):
        share = count / primary["episodes_measured"] if primary["episodes_measured"] else 0
        print(f"  {reason:<24} {count:>6,}  {share:.2%}")
    print()

    infra = report["infrastructure_correctness"]
    print("INFRASTRUCTURE CORRECTNESS  (non-zero here invalidates the quality numbers)")
    for label, key in (
        ("generation infra failures", "generation_infrastructure_failures"),
        ("tool infra failures", "tool_infrastructure_failures"),
        ("evaluator infra failures", "evaluator_infrastructure_failures"),
        ("gold query failures", "gold_query_failures"),
        ("missing trajectories", "missing_trajectories"),
        ("episodes without trace id", "episodes_without_trace_id"),
        ("steps without trace id", "steps_without_trace_id"),
        ("step-count disagreements", "step_count_disagreements"),
    ):
        print(f"  {label:<34} {infra[key]:,}")
    if infra["duplicate_task_ids"]:
        print(f"  duplicate task ids                 {infra['duplicate_task_ids']}")
    print(f"  total step records                 {infra['total_step_records']:,}")

    if "trace_check" in report:
        check = report["trace_check"]
        print()
        print("TRACE CROSS-CHECK (Elasticsearch)")
        if not check.get("available"):
            print(f"  unavailable: {check.get('error')}")
        else:
            print(f"  span documents for this run      {check['span_documents']:,}")
            for name, count in sorted(
                check.get("by_span_name", {}).items(), key=lambda item: -item[1]
            ):
                print(f"    {name:<24} {count:,}")
            reconciliation = check.get("reconciliation", {})
            if reconciliation:
                print("  trace vs trajectory:")
                for name, entry in reconciliation.items():
                    mark = "ok " if entry["expected"] == entry["found"] else "MISMATCH"
                    print(
                        f"    {mark} {name:<22} expected {entry['expected']:,}  "
                        f"found {entry['found']:,}"
                    )
                print(f"  matches_trajectory: {check['matches_trajectory']}")

    print()
    print(f"run_is_clean: {report['run_is_clean']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--root", default=str(DEFAULT_RUN_ROOT))
    parser.add_argument(
        "--check-traces",
        action="store_true",
        help="Cross-check span counts against Elasticsearch.",
    )
    parser.add_argument("--elasticsearch-url", default=DEFAULT_ELASTICSEARCH_URL)
    parser.add_argument("--trace-index", default=DEFAULT_TRACE_INDEX)
    parser.add_argument("--output", default=None, help="Where to write the JSON report.")
    args = parser.parse_args()

    trace_check = None
    if args.check_traces:
        trace_check = count_run_spans(
            args.run_id, args.elasticsearch_url, args.trace_index
        )

    report = build_report(args.run_id, Path(args.root), trace_check)
    print_report(report)

    output = Path(args.output) if args.output else (
        Path(args.root) / args.run_id / "p0_metrics.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
