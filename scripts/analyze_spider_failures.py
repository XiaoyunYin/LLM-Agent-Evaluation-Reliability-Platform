"""Failure analysis for a Spider benchmark run, with explicit classification rules.

`report_spider_metrics.py` reports what happened. This asks *why*, and it does so
with rules written down and applied by code, so a category like "empty-result
confusion" is reproducible rather than an impression formed by reading a few
trajectories.

Three separations this script exists to enforce:

1. **Tool-call-level vs episode-level errors.** A failed `execute_sql` is one tool
   call going wrong. A `SQL_ERROR` termination is an episode ending because its
   *final submitted* query does not run. An episode can contain the first and not
   the second - it can recover. Averaging them together would be wrong in both
   directions.

2. **Complete termination accounting.** Every one of the seven P0 termination
   reasons is printed, including the ones that are zero, and the total is asserted
   against the episode count. A category omitted because it is empty is a category
   a reader cannot confirm is empty.

3. **Classified vs speculated.** Each failure category below states its rule.

Usage:
    python scripts/analyze_spider_failures.py --run-id spider_full__p0_v1
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.spider.evaluator import VerificationOutcome, verify_sql  # noqa: E402
from backend.app.spider.loader import load_spider_tasks  # noqa: E402
from backend.app.spider.trajectory import (  # noqa: E402
    DEFAULT_RUN_ROOT,
    TerminationReason,
    TrajectoryStore,
    open_jsonl,
)

# Every P0 termination reason, in report order. Printed even when zero.
ALL_TERMINATIONS = [reason.value for reason in TerminationReason]

CLASSIFICATION_RULES = {
    "empty_result_loop_broad": (
        "Episode terminated MAX_STEPS AND executed at least one execute_sql call "
        "that returned row_count == 0 with error == None (a valid query returning "
        "no rows)."
    ),
    "empty_result_loop_strict": (
        "Episode terminated MAX_STEPS AND executed at least two execute_sql calls "
        "that each returned row_count == 0 with error == None."
    ),
    "abandoned_a_correct_query": (
        "Episode terminated MAX_STEPS AND at least one query it executed during "
        "the episode passes the official evaluator against gold. Established by "
        "re-running each executed query through verify_sql, not by inspection."
    ),
}


def load_run(run_id: str, root: Path) -> dict[str, Any]:
    store = TrajectoryStore(run_id, root)
    if not store.episodes_path.exists():
        raise SystemExit(f"No episodes at {store.episodes_path}")

    episodes = list(store.iter_episodes())
    steps = list(store.iter_steps())

    tool_results: dict[str, Any] = {}
    with open_jsonl(store.payloads_path) as handle:
        for line in handle:
            line = line.strip()
            if not line or '"tool_result"' not in line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("kind") == "tool_result":
                tool_results[record["ref"]] = record.get("data") or {}

    config = (
        json.loads(store.config_path.read_text(encoding="utf-8"))
        if store.config_path.exists()
        else {}
    )
    return {
        "store": store,
        "config": config,
        "episodes": episodes,
        "steps": steps,
        "tool_results": tool_results,
    }


def analyze(run_id: str, root: Path, verify_abandoned: bool) -> dict[str, Any]:
    run = load_run(run_id, root)
    episodes = run["episodes"]
    steps = run["steps"]
    tool_results = run["tool_results"]
    config = run["config"]

    steps_by_episode: dict[str, list[dict]] = collections.defaultdict(list)
    for step in steps:
        steps_by_episode[step["episode_id"]].append(step)

    # -- 1. complete termination accounting -------------------------------
    counts = collections.Counter(e["termination_reason"] for e in episodes)
    termination_table = {reason: counts.get(reason, 0) for reason in ALL_TERMINATIONS}
    unexpected = sorted(set(counts) - set(ALL_TERMINATIONS))
    termination_total = sum(termination_table.values())

    # -- 2. step decomposition --------------------------------------------
    successes = [e for e in episodes if e["termination_reason"] == "SUCCESS"]

    def summarize(values: list[float]) -> dict[str, float | None]:
        if not values:
            return {"mean": None, "median": None, "min": None, "max": None}
        import statistics

        return {
            "mean": statistics.fmean(values),
            "median": statistics.median(values),
            "min": min(values),
            "max": max(values),
        }

    step_decomposition = {
        "definitions": {
            "model_turns": "One completed call to the model API. This is what max_steps caps.",
            "tool_calls": "One tool invocation record (inspect_schema, execute_sql, or submit_answer).",
            "trajectory_records": "Rows written to steps.jsonl = model_turns + tool_calls.",
        },
        "max_steps_config": config.get("max_steps"),
        "max_steps_is_a_model_turn_cap": True,
        "successful_tasks": {
            "model_turns": summarize([float(e["model_steps"]) for e in successes]),
            "tool_calls": summarize([float(e["tool_steps"]) for e in successes]),
            "trajectory_records": summarize([float(e["total_steps"]) for e in successes]),
            "schema_inspections": summarize([float(e["schema_inspections"]) for e in successes]),
            "sql_executions": summarize([float(e["sql_executions"]) for e in successes]),
        },
        "all_tasks": {
            "model_turns": summarize([float(e["model_steps"]) for e in episodes]),
            "tool_calls": summarize([float(e["tool_steps"]) for e in episodes]),
            "trajectory_records": summarize([float(e["total_steps"]) for e in episodes]),
        },
        "totals": {
            "model_turns": sum(e["model_steps"] for e in episodes),
            "tool_calls": sum(e["tool_steps"] for e in episodes),
            "trajectory_records": sum(e["total_steps"] for e in episodes),
            "step_records_on_file": len(steps),
        },
        "identity_holds": all(
            e["total_steps"] == e["model_steps"] + e["tool_steps"] for e in episodes
        ),
        "episodes_reaching_the_model_turn_cap": sum(
            1 for e in episodes if e["model_steps"] >= (config.get("max_steps") or 10)
        ),
    }

    # -- 3. tool-call level vs episode level -------------------------------
    tool_steps = [s for s in steps if s["step_type"] == "tool"]
    by_tool = collections.Counter(s["tool_name"] for s in tool_steps)
    failures_by_tool = collections.Counter(
        s["tool_name"] for s in tool_steps if s["tool_success"] is False
    )

    sql_calls = [s for s in tool_steps if s["tool_name"] == "execute_sql"]
    sql_failures = [s for s in sql_calls if s["tool_success"] is False]
    episodes_with_sql_error = {s["episode_id"] for s in sql_failures}
    episode_termination = {e["episode_id"]: e["termination_reason"] for e in episodes}

    recovered = sorted(
        episode_termination[eid]
        for eid in episodes_with_sql_error
        if episode_termination[eid] == "SUCCESS"
    )

    tool_vs_episode = {
        "tool_call_level": {
            "definition": (
                "Counted per tool invocation. A failure here is one call going "
                "wrong; the episode may recover from it."
            ),
            "calls_by_tool": dict(by_tool),
            "failures_by_tool": dict(failures_by_tool),
            "execute_sql_calls": len(sql_calls),
            "execute_sql_failures": len(sql_failures),
            "execute_sql_error_rate": (
                len(sql_failures) / len(sql_calls) if sql_calls else None
            ),
            "execute_sql_failure_messages": [
                {
                    "task_id": next(
                        e["task_id"] for e in episodes if e["episode_id"] == s["episode_id"]
                    ),
                    "error": (tool_results.get(s["tool_result_ref"]) or {}).get("error"),
                }
                for s in sql_failures
            ],
        },
        "episode_level": {
            "definition": (
                "Counted per episode, from termination_reason. SQL_ERROR means the "
                "episode's FINAL SUBMITTED query does not execute."
            ),
            "sql_error_terminations": termination_table["SQL_ERROR"],
            "episodes_containing_at_least_one_execute_sql_failure": len(
                episodes_with_sql_error
            ),
            "of_those_that_still_succeeded": len(recovered),
            "episodes_containing_any_tool_failure_that_still_succeeded": len(
                {
                    s["episode_id"]
                    for s in tool_steps
                    if s["tool_success"] is False
                    and episode_termination[s["episode_id"]] == "SUCCESS"
                }
            ),
        },
        "why_they_differ": (
            "A failed execute_sql is a tool-call event the agent can see and fix. "
            "SQL_ERROR is an episode outcome. These are different denominators "
            "(tool calls vs episodes) and must not appear in the same table."
        ),
    }

    # -- 4. MAX_STEPS classification ---------------------------------------
    max_step_episodes = [e for e in episodes if e["termination_reason"] == "MAX_STEPS"]
    tasks = {t.task_id: t for t in load_spider_tasks(config.get("split") or "dev")}

    broad: list[str] = []
    strict: list[str] = []
    abandoned: list[dict[str, str]] = []

    for episode in max_step_episodes:
        calls = [
            (step, tool_results.get(step["tool_result_ref"]) or {})
            for step in steps_by_episode[episode["episode_id"]]
            if step["tool_name"] == "execute_sql"
        ]
        zero_rows = [
            (step, result)
            for step, result in calls
            if result.get("row_count") == 0 and result.get("error") is None
        ]
        if zero_rows:
            broad.append(episode["task_id"])
        if len(zero_rows) >= 2:
            strict.append(episode["task_id"])

        if verify_abandoned:
            task = tasks.get(episode["task_id"])
            if task is None:
                continue
            for step, _ in calls:
                query = (step.get("tool_args") or {}).get("query")
                if not query:
                    continue
                verification = verify_sql(
                    query, task.gold_query, task.database_path,
                    task.task_id, task.database_id,
                )
                if verification.outcome is VerificationOutcome.PASS:
                    abandoned.append({"task_id": episode["task_id"], "query": query})
                    break

    max_steps_analysis = {
        "total_max_step_episodes": len(max_step_episodes),
        "rules": CLASSIFICATION_RULES,
        "empty_result_loop_broad": {
            "count": len(broad),
            "share_of_max_steps": len(broad) / len(max_step_episodes) if max_step_episodes else None,
            "task_ids": sorted(broad),
        },
        "empty_result_loop_strict": {
            "count": len(strict),
            "share_of_max_steps": len(strict) / len(max_step_episodes) if max_step_episodes else None,
            "task_ids": sorted(strict),
        },
        "abandoned_a_correct_query": {
            "verified": verify_abandoned,
            "count": len(abandoned) if verify_abandoned else None,
            "share_of_max_steps": (
                len(abandoned) / len(max_step_episodes)
                if verify_abandoned and max_step_episodes
                else None
            ),
            "task_ids": sorted(row["task_id"] for row in abandoned),
            "examples": abandoned[:5],
        },
        "upper_bound_if_all_max_steps_were_solved": {
            "current_success_rate": termination_table["SUCCESS"] / len(episodes),
            "ceiling": (termination_table["SUCCESS"] + len(max_step_episodes)) / len(episodes),
            "note": (
                "A ceiling, not a forecast. It assumes every max-step episode would "
                "convert to a pass, which the data does not establish."
            ),
        },
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "episodes": len(episodes),
        "config": {
            key: config.get(key)
            for key in (
                "dataset_version", "model_version", "prompt_version",
                "tool_schema_version", "agent_version", "adapter_version",
                "max_steps", "temperature", "code_commit_sha", "stage", "is_mock",
            )
        },
        "termination_breakdown": {
            "counts": termination_table,
            "total": termination_total,
            "episodes_on_file": len(episodes),
            "sums_exactly": termination_total == len(episodes),
            "unexpected_reasons": unexpected,
        },
        "step_decomposition": step_decomposition,
        "tool_vs_episode_errors": tool_vs_episode,
        "max_steps_analysis": max_steps_analysis,
    }


def print_report(report: dict[str, Any]) -> None:
    print(f"Failure analysis - run {report['run_id']}\n")

    breakdown = report["termination_breakdown"]
    print("TERMINATION BREAKDOWN (all P0 reasons, including zeros)")
    for reason, count in breakdown["counts"].items():
        share = count / report["episodes"] if report["episodes"] else 0
        print(f"  {reason:<22} {count:>6,}  {share:6.2%}")
    print(f"  {'TOTAL':<22} {breakdown['total']:>6,}")
    print(f"  sums exactly to episodes on file: {breakdown['sums_exactly']}")
    if breakdown["unexpected_reasons"]:
        print(f"  UNEXPECTED: {breakdown['unexpected_reasons']}")
    print()

    steps = report["step_decomposition"]
    print("STEP DECOMPOSITION  (the three quantities that must not be conflated)")
    for name, text in steps["definitions"].items():
        print(f"  {name:<20} {text}")
    print(f"  max_steps={steps['max_steps_config']} caps MODEL TURNS "
          f"(episodes reaching it: {steps['episodes_reaching_the_model_turn_cap']})")
    print()
    print("  successful tasks:")
    for name in ("model_turns", "tool_calls", "trajectory_records"):
        block = steps["successful_tasks"][name]
        print(f"    {name:<20} mean {block['mean']:.2f}  median {block['median']:.2f}  "
              f"range {block['min']:.0f}-{block['max']:.0f}")
    print("  all tasks:")
    for name in ("model_turns", "tool_calls", "trajectory_records"):
        block = steps["all_tasks"][name]
        print(f"    {name:<20} mean {block['mean']:.2f}  median {block['median']:.2f}")
    print(f"  totals: {steps['totals']}")
    print(f"  identity trajectory_records == model_turns + tool_calls: {steps['identity_holds']}")
    print()

    errors = report["tool_vs_episode_errors"]
    print("TOOL-CALL LEVEL vs EPISODE LEVEL")
    call = errors["tool_call_level"]
    print(f"  calls by tool         {call['calls_by_tool']}")
    print(f"  failures by tool      {call['failures_by_tool']}")
    print(f"  execute_sql error rate {call['execute_sql_failures']}/{call['execute_sql_calls']} "
          f"= {call['execute_sql_error_rate']:.4f}   <- TOOL-CALL denominator")
    ep = errors["episode_level"]
    print(f"  SQL_ERROR terminations {ep['sql_error_terminations']}   <- EPISODE denominator")
    print(f"  episodes with >=1 execute_sql failure: "
          f"{ep['episodes_containing_at_least_one_execute_sql_failure']}, "
          f"of which still succeeded: {ep['of_those_that_still_succeeded']}")
    print()

    ms = report["max_steps_analysis"]
    print(f"MAX_STEPS ANALYSIS  ({ms['total_max_step_episodes']} episodes)")
    for key in ("empty_result_loop_broad", "empty_result_loop_strict", "abandoned_a_correct_query"):
        block = ms[key]
        if block["count"] is None:
            print(f"  {key:<28} not computed (--no-verify-abandoned)")
            continue
        print(f"  {key:<28} {block['count']:>3} / {ms['total_max_step_episodes']} "
              f"= {block['share_of_max_steps']:.1%}")
    print(f"  rule definitions are recorded in the JSON artifact")
    ceiling = ms["upper_bound_if_all_max_steps_were_solved"]
    print(f"  success rate {ceiling['current_success_rate']:.4f}, "
          f"ceiling if all max-step episodes converted {ceiling['ceiling']:.4f}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--root", default=str(DEFAULT_RUN_ROOT))
    parser.add_argument(
        "--no-verify-abandoned",
        action="store_true",
        help="Skip re-verifying executed queries (the slow part).",
    )
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    report = analyze(args.run_id, Path(args.root), not args.no_verify_abandoned)
    print_report(report)

    output = Path(args.output) if args.output else (
        Path(args.root) / args.run_id / "failure_analysis.json"
    )
    output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
