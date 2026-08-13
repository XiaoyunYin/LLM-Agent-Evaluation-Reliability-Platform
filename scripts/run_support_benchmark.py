"""Run the P3 support benchmark.

Same execution discipline as the Spider runner: adopted flags resolved from
`config/adopted_agent_flags.json` and recorded with their provenance, rate limits
treated as a halting infrastructure state rather than a model error, episodes
checkpointed and resumable, and every run config carrying the versions its results
depend on.

Usage:
    python scripts/run_support_benchmark.py --run-id support_cal_1 --repeat 1
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

from opentelemetry import context as otel_context  # noqa: E402
from opentelemetry.trace import set_span_in_context  # noqa: E402

from backend.app.spider.trajectory import (  # noqa: E402
    AgentEpisode,
    HALTING_TERMINATIONS,
    TerminationReason,
    TrajectoryStore,
)
from backend.app.support.agent import (  # noqa: E402
    AGENT_VERSION,
    PROMPT_VERSION,
    SUPPORT_PROMPTS,
    SupportAgentConfig,
    SupportEpisodeContext,
    build_graph,
)
from backend.app.support.environment import SupportEnvironment  # noqa: E402
from backend.app.support.normalize import NORMALIZATION_VERSION  # noqa: E402
from backend.app.support.schema import SCHEMA_VERSION, build_fixture  # noqa: E402
from backend.app.support.tasks import TASK_FAMILY_VERSION, build_tasks  # noqa: E402
from backend.app.support.tools import (  # noqa: E402
    CONTRACT_STAGE,
    TOOL_SCHEMA_VERSION,
)
from backend.app.support.verifier import VERIFIER_VERSION, verify  # noqa: E402
from backend.app.tracing import (  # noqa: E402
    SERVICE_LAYER_GATEWAY,
    SERVICE_LAYER_JUDGE,
    configure_tracing,
    current_trace_id,
    force_flush_traces,
    get_tracer,
)

FIXTURE_PATH = REPO_ROOT / "datasets" / "support" / "support_fixture.sqlite"
ADOPTED_FLAGS_PATH = REPO_ROOT / "config" / "adopted_agent_flags.json"
RUN_ROOT = REPO_ROOT / "runs" / "support_benchmark"


def adopted_flags() -> dict[str, Any]:
    document = json.loads(ADOPTED_FLAGS_PATH.read_text(encoding="utf-8"))
    return {name: entry["value"] for name, entry in document.get("adopted", {}).items()}


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True,
            stderr=subprocess.DEVNULL).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def git_dirty() -> bool:
    try:
        return bool(subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=REPO_ROOT, text=True,
            stderr=subprocess.DEVNULL).strip())
    except Exception:  # noqa: BLE001
        return False


def run_episode(agent_graph, task_entry, config, client, run_id, store, workspace):
    """One episode: isolated environment, agent, verifier, persistence."""
    spec = task_entry["spec"]
    episode_id = uuid.uuid4().hex[:16]
    tracer = get_tracer()
    started = time.perf_counter()

    with tracer.start_as_current_span("agent.episode") as episode_span:
        episode_span.set_attribute("run.id", run_id)
        episode_span.set_attribute("episode.id", episode_id)
        episode_span.set_attribute("task.id", spec.task_id)
        episode_span.set_attribute("task.family", spec.family)
        episode_span.set_attribute("tool_schema.version", TOOL_SCHEMA_VERSION)
        trace_id = current_trace_id()

        environment = SupportEnvironment(FIXTURE_PATH, episode_id, workspace)
        context = SupportEpisodeContext(
            episode_id=episode_id, run_id=run_id, task=spec,
            environment=environment, store=store, config=config, client=client,
        )

        episode_error = None
        final_state: dict[str, Any] = {}
        try:
            environment.setup()
            store.store_payload(f"{episode_id}:before_state", "before_state",
                                environment.before_state)
            initial = {
                "task_id": spec.task_id,
                "messages": [
                    {"role": "system", "content": SUPPORT_PROMPTS[config.prompt_version]},
                    {"role": "user", "content": spec.prompt},
                ],
                "tool_calls": [], "step_index": 0, "model_step_count": 0,
                "finished": False, "termination_reason": None,
                "input_tokens": 0, "output_tokens": 0, "estimated_cost": 0.0,
            }
            final_state = agent_graph.invoke(
                initial,
                config={"configurable": {"episode_context": context},
                        "recursion_limit": config.max_steps * 2 + 10},
            )
        except Exception as error:  # noqa: BLE001
            episode_error = f"{type(error).__name__}: {error}"
            final_state = {**final_state, "termination_reason": TerminationReason.TOOL_ERROR.value}

        changes = environment.state_diff()
        store.store_payload(f"{episode_id}:after_state", "after_state", environment.after_state)
        store.store_payload(f"{episode_id}:state_diff", "state_diff", changes)

        with tracer.start_as_current_span("verifier.state") as span:
            span.set_attribute("service.layer", SERVICE_LAYER_JUDGE)
            span.set_attribute("run.id", run_id)
            span.set_attribute("episode.id", episode_id)
            verification = verify(spec, changes, environment.after_state)
            span.set_attribute("verification.success", verification.passed)
        environment.cleanup()

        raw = final_state.get("termination_reason")
        if raw in {TerminationReason.MODEL_ERROR.value,
                   TerminationReason.RATE_LIMITED.value,
                   TerminationReason.TOOL_ERROR.value}:
            termination = TerminationReason(raw)
        elif raw == TerminationReason.MAX_STEPS.value:
            termination = TerminationReason.MAX_STEPS
        elif verification.passed:
            termination = TerminationReason.SUCCESS
        elif not final_state.get("finished"):
            termination = TerminationReason.INCOMPLETE
        else:
            termination = TerminationReason.VERIFICATION_FAILED

        episode_span.set_attribute("termination.reason", termination.value)
        for step in context.steps:
            store.record_step(step)

        episode = AgentEpisode(
            episode_id=episode_id, run_id=run_id, task_id=spec.task_id,
            dataset_version=f"support:{spec.fixture_sha256[:12]}",
            model_version=config.model, prompt_version=config.prompt_version,
            tool_schema_version=TOOL_SCHEMA_VERSION,
            status="completed" if episode_error is None else "failed",
            final_sql=None,
            verification_result=verification.model_dump(mode="json"),
            termination_reason=termination,
            total_steps=len(context.steps),
            model_steps=sum(1 for s in context.steps if s.step_type.value == "model"),
            tool_steps=sum(1 for s in context.steps if s.step_type.value == "tool"),
            schema_inspections=context.counters.get("read_calls", 0),
            sql_executions=context.counters.get("effectful_calls", 0),
            sql_execution_errors=context.counters.get("effectful_call_failures", 0),
            bad_argument_tool_calls=(
                context.counters.get("invalid_typed_calls", 0)
                + context.counters.get("malformed_argument_calls", 0)
            ),
            input_tokens=sum(s.input_tokens for s in context.steps),
            cached_input_tokens=sum(s.cached_input_tokens for s in context.steps),
            output_tokens=sum(s.output_tokens for s in context.steps),
            estimated_cost=sum(s.estimated_cost for s in context.steps),
            latency_ms=(time.perf_counter() - started) * 1000.0,
            api_latency_ms=sum(s.api_latency_ms for s in context.steps),
            retry_wait_ms=sum(s.retry_wait_ms for s in context.steps),
            trace_id=trace_id,
            error=episode_error or context.model_error,
        )
        store.record_episode(episode)
        return episode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--tickets", type=int, default=60)
    parser.add_argument("--stage", default="calibration")
    parser.add_argument("--empty-result-policy", default=None,
                        choices=["baseline", "accept_empty"])
    parser.add_argument("--schema-repair", action="store_true")
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    os.environ.setdefault("OTEL_CONSOLE_EXPORTER", "false")
    configure_tracing()

    adopted = adopted_flags()
    policy = args.empty_result_policy or adopted.get("empty_result_policy", "accept_empty")
    policy_source = ("explicit --empty-result-policy" if args.empty_result_policy
                     else "adopted default (config/adopted_agent_flags.json)")
    deviates = policy != adopted.get("empty_result_policy")

    fixture_sha = build_fixture(FIXTURE_PATH, args.tickets)
    tasks = build_tasks(FIXTURE_PATH, fixture_sha, SCHEMA_VERSION)
    if args.limit:
        tasks = tasks[: args.limit]

    config = SupportAgentConfig(
        model=args.model, empty_result_policy=policy,
        schema_repair_enabled=args.schema_repair,
    )
    if args.max_steps:
        config.max_steps = args.max_steps

    from openai import OpenAI

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is not set.")
    client = OpenAI(api_key=api_key, max_retries=0)

    store = TrajectoryStore(args.run_id, RUN_ROOT)
    if args.no_resume:
        store.reset()
        already, pruned = set(), 0
    else:
        pruned = store.prune_infrastructure_episodes()
        already = store.completed_task_ids()
    pending = [t for t in tasks if t["spec"].task_id not in already]

    store.write_config({
        "run_id": args.run_id, "stage": args.stage,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "benchmark": "support", "contract_stage": CONTRACT_STAGE,
        "fixture_sha256": fixture_sha,
        "schema_version": SCHEMA_VERSION,
        "normalization_version": NORMALIZATION_VERSION,
        "verifier_version": VERIFIER_VERSION,
        "tool_schema_version": TOOL_SCHEMA_VERSION,
        "task_family_version": TASK_FAMILY_VERSION,
        "agent_version": AGENT_VERSION, "prompt_version": PROMPT_VERSION,
        "model_version": args.model, "temperature": config.temperature,
        "top_p": config.top_p, "seed": config.seed,
        "max_steps": config.max_steps, "concurrency": args.concurrency,
        "empty_result_policy": policy,
        "empty_result_policy_source": policy_source,
        "schema_repair_enabled": args.schema_repair,
        "adopted_flags": adopted, "deviates_from_adopted_flags": deviates,
        "selected_task_count": len(tasks),
        "selected_task_ids": [t["spec"].task_id for t in tasks],
        "code_commit_sha": git_sha(), "code_working_tree_dirty": git_dirty(),
    })

    print(f"Run {args.run_id} [{args.stage}]")
    print(f"  model {args.model}  max_steps {config.max_steps}  concurrency {args.concurrency}")
    print(f"  empty_result {policy} ({policy_source})")
    if deviates:
        print("  *** DEVIATES from adopted behaviour ***")
    print(f"  tasks {len(tasks)}  pending {len(pending)}"
          + (f"  pruned {pruned}" if pruned else ""))

    if not pending:
        print("Nothing to run.")
        return 0

    graph = build_graph()
    workspace = REPO_ROOT / "runs" / "_support_run_tmp"
    tracer = get_tracer()
    counts: dict[str, int] = {}
    passed = 0
    total_cost = 0.0
    started = time.perf_counter()

    with tracer.start_as_current_span("eval.run") as run_span:
        run_span.set_attribute("service.layer", SERVICE_LAYER_GATEWAY)
        run_span.set_attribute("run.id", args.run_id)
        run_span.set_attribute("benchmark", "support")
        run_context = set_span_in_context(run_span)
        halt = threading.Event()
        lock = threading.Lock()
        done = 0

        def execute(entry):
            if halt.is_set():
                return entry, None
            token = otel_context.attach(run_context)
            try:
                return entry, run_episode(graph, entry, config, client,
                                          args.run_id, store, workspace)
            finally:
                otel_context.detach(token)

        def record(entry, episode):
            nonlocal passed, total_cost, done
            if episode is None:
                return
            if episode.termination_reason in HALTING_TERMINATIONS:
                halt.set()
            with lock:
                done += 1
                reason = episode.termination_reason.value
                counts[reason] = counts.get(reason, 0) + 1
                total_cost += episode.estimated_cost
                if episode.termination_reason is TerminationReason.SUCCESS:
                    passed += 1
                if not args.quiet:
                    mark = "PASS" if episode.termination_reason is TerminationReason.SUCCESS else "    "
                    print(f"  [{done:>3}/{len(pending)}] {mark} {entry['spec'].task_id:<22}"
                          f"{reason:<22} turns={episode.model_steps:<3} ${episode.estimated_cost:.5f}")

        if args.concurrency <= 1:
            for entry in pending:
                if halt.is_set():
                    break
                record(*execute(entry))
        else:
            with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
                futures = [pool.submit(execute, entry) for entry in pending]
                for future in as_completed(futures):
                    record(*future.result())

        run_span.set_attribute("run.passed", passed)

    force_flush_traces()
    elapsed = time.perf_counter() - started
    total = sum(counts.values())

    print(f"\nRan {total} episodes in {elapsed/60:.1f} min")
    print(f"  passed         {passed}/{max(total,1)} ({passed/max(total,1):.1%})")
    print(f"  estimated cost ${total_cost:.4f}")
    for reason, count in sorted(counts.items(), key=lambda i: -i[1]):
        print(f"    {reason:<24} {count}")

    import shutil
    shutil.rmtree(workspace, ignore_errors=True)

    if counts.get(TerminationReason.RATE_LIMITED.value):
        print("\nHALTED on rate limit; re-run the same command to resume.")
        return 75
    return 0


if __name__ == "__main__":
    sys.exit(main())
