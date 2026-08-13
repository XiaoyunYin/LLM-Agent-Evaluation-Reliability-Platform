"""Replay every reference solution through the real runtime. No model calls.

This is the integration check that has to pass before an agent is ever pointed at
the benchmark. It exercises the production path — real tools, real state, real
persistence, real spans — with the *model replaced by a script*, so any failure is
unambiguously an infrastructure defect rather than a model one.

Checks, per task:

- every reference tool call executes successfully
- the resulting state diff verifies PASS
- a trajectory step is persisted for every call
- call identities are unique and gap-free within the episode
- effectful calls are individually identifiable and carry their mutation
- before/after state references and the normalized diff are persisted
- the adopted-flag provenance is recorded

It also measures the reference trajectory-length distribution, which is what the
model-turn budget is derived from rather than guessed.

Usage:
    python scripts/replay_support_references.py
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

from backend.app.spider.trajectory import TrajectoryStore  # noqa: E402
from backend.app.support.agent import AGENT_VERSION, PROMPT_VERSION  # noqa: E402
from backend.app.support.environment import SupportEnvironment  # noqa: E402
from backend.app.support.normalize import NORMALIZATION_VERSION  # noqa: E402
from backend.app.support.schema import (  # noqa: E402
    DEFAULT_TICKET_COUNT,
    SCHEMA_VERSION,
    build_fixture,
)
from backend.app.support.tasks import TASK_FAMILY_VERSION, build_tasks  # noqa: E402
from backend.app.support.tools import (  # noqa: E402
    CONTRACT_STAGE,
    EFFECTFUL_TOOLS,
    TOOL_SCHEMA_VERSION,
    ToolCallIdentity,
    call_tool,
)
from backend.app.support.verifier import VERIFIER_VERSION, verify  # noqa: E402
from backend.app.tracing import configure_tracing, current_trace_id, get_tracer  # noqa: E402

FIXTURE_PATH = REPO_ROOT / "datasets" / "support" / "support_fixture.sqlite"
ADOPTED_FLAGS = REPO_ROOT / "config" / "adopted_agent_flags.json"
RESULT_DIR = REPO_ROOT / "runs" / "support_reference_replay"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickets", type=int, default=DEFAULT_TICKET_COUNT)
    parser.add_argument("--run-id", default="support_reference_replay")
    args = parser.parse_args()

    configure_tracing()
    fixture_sha = build_fixture(FIXTURE_PATH, args.tickets)
    tasks = build_tasks(FIXTURE_PATH, fixture_sha, SCHEMA_VERSION)

    adopted = json.loads(ADOPTED_FLAGS.read_text(encoding="utf-8"))["adopted"]
    empty_policy = adopted["empty_result_policy"]["value"]

    store = TrajectoryStore(args.run_id)
    store.reset()
    workspace = REPO_ROOT / "runs" / "_support_replay_tmp"

    tracer = get_tracer()
    results: list[dict[str, Any]] = []
    problems: list[str] = []

    with tracer.start_as_current_span("eval.run") as run_span:
        run_span.set_attribute("run.id", args.run_id)
        run_span.set_attribute("run.kind", "reference_replay")
        run_span.set_attribute("tool_schema.version", TOOL_SCHEMA_VERSION)

        for entry in tasks:
            spec, reference = entry["spec"], entry["reference"]
            episode_id = f"ref_{spec.task_id}"

            with tracer.start_as_current_span("agent.episode") as episode_span:
                episode_span.set_attribute("run.id", args.run_id)
                episode_span.set_attribute("episode.id", episode_id)
                episode_span.set_attribute("task.id", spec.task_id)
                trace_id = current_trace_id()

                environment = SupportEnvironment(FIXTURE_PATH, episode_id, workspace)
                environment.setup()

                before_ref = store.store_payload(
                    f"{episode_id}:before_state", "before_state", environment.before_state
                )

                identities: list[str] = []
                effectful_seen = 0
                call_failures: list[str] = []

                for index, (name, arguments) in enumerate(reference):
                    identity = ToolCallIdentity(
                        episode_id=episode_id, step_index=index, call_index=index
                    )
                    with tracer.start_as_current_span(f"tool.{name}") as span:
                        span.set_attribute("run.id", args.run_id)
                        span.set_attribute("episode.id", episode_id)
                        span.set_attribute("tool.name", name)
                        span.set_attribute("tool.call_key", identity.key())
                        result = call_tool(
                            environment, name, dict(arguments), identity,
                            empty_result_policy=empty_policy,
                        )
                        span.set_attribute("tool.success", result.success)

                    identities.append(identity.key())
                    if name in EFFECTFUL_TOOLS:
                        effectful_seen += 1
                    if not result.success:
                        call_failures.append(f"{name}: {result.error}")

                    store.store_payload(
                        f"{episode_id}:call:{identity.call_index:03d}", "tool_result",
                        {
                            "identity": identity.model_dump(),
                            "tool": name,
                            "tool_schema_version": result.tool_schema_version,
                            "arguments": arguments,
                            "result": result.model_visible,
                            "error_kind": result.error_kind,
                            "effectful": result.effectful,
                            "mutation": result.mutation,
                        },
                    )

                changes = environment.state_diff()
                after_ref = store.store_payload(
                    f"{episode_id}:after_state", "after_state", environment.after_state
                )
                diff_ref = store.store_payload(
                    f"{episode_id}:state_diff", "state_diff", changes
                )
                verification = verify(spec, changes, environment.after_state)
                environment.cleanup()

                episode_span.set_attribute("verification.success", verification.passed)

            unique = len(set(identities)) == len(identities)
            model_turns = len(reference)

            row = {
                "task_id": spec.task_id,
                "family": spec.family,
                "reference_calls": len(reference),
                "effectful_calls": effectful_seen,
                "identities_unique": unique,
                "call_failures": call_failures,
                "state_changes": len(changes),
                "verifier_outcome": verification.outcome.value,
                "passed": verification.passed,
                "before_ref": before_ref,
                "after_ref": after_ref,
                "diff_ref": diff_ref,
                "trace_id": trace_id,
                "model_turns_equivalent": model_turns,
            }
            results.append(row)

            if not verification.passed:
                problems.append(f"{spec.task_id}: verifier {verification.outcome.value}")
            if call_failures:
                problems.append(f"{spec.task_id}: tool failures {call_failures}")
            if not unique:
                problems.append(f"{spec.task_id}: duplicate call identities")
            if not trace_id:
                problems.append(f"{spec.task_id}: no trace id")

    lengths = [r["reference_calls"] for r in results]
    by_family: dict[str, list[int]] = {}
    for row in results:
        by_family.setdefault(row["family"], []).append(row["reference_calls"])

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": args.run_id,
        "model_calls_made": 0,
        "fixture_sha256": fixture_sha,
        "versions": {
            "schema": SCHEMA_VERSION, "normalization": NORMALIZATION_VERSION,
            "verifier": VERIFIER_VERSION, "tools": TOOL_SCHEMA_VERSION,
            "contract_stage": CONTRACT_STAGE, "task_families": TASK_FAMILY_VERSION,
            "agent": AGENT_VERSION, "prompt": PROMPT_VERSION,
        },
        "adopted_flags": {name: entry["value"] for name, entry in adopted.items()},
        "empty_result_policy_used": empty_policy,
        "tasks": len(results),
        "all_passed": not problems,
        "problems": problems,
        "reference_trajectory_lengths": {
            "min": min(lengths), "max": max(lengths),
            "mean": statistics.fmean(lengths),
            "median": statistics.median(lengths),
            "by_family": {k: {"min": min(v), "max": max(v), "n": len(v)}
                          for k, v in sorted(by_family.items())},
        },
        "results": results,
    }

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    output = RESULT_DIR / "reference_replay.json"
    output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print(f"Reference replay - {len(results)} tasks, ZERO model calls\n")
    print(f"  adopted flags used      {report['adopted_flags']}")
    print(f"  all references pass     {report['all_passed']}")
    print(f"  effectful calls total   {sum(r['effectful_calls'] for r in results)}")
    print(f"  trajectory steps        {len(list(store.iter_steps()))} "
          f"(payload-only replay; steps are written by the agent runtime)")
    print()
    print("  reference trajectory length (tool calls):")
    lengths_block = report["reference_trajectory_lengths"]
    print(f"    min {lengths_block['min']}  median {lengths_block['median']}  "
          f"max {lengths_block['max']}  mean {lengths_block['mean']:.2f}")
    for family, block in lengths_block["by_family"].items():
        print(f"    {family:<26} n={block['n']:<3} {block['min']}-{block['max']}")
    if problems:
        print("\n  PROBLEMS:")
        for problem in problems[:15]:
            print(f"    {problem}")
    print(f"\nWrote {output}")

    import shutil
    shutil.rmtree(workspace, ignore_errors=True)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
