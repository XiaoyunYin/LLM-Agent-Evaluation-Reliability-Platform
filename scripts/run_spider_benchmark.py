"""Run the Spider SQL-agent benchmark (P0 plan, Steps 9, 13, 14, 15).

Staged by design. The same script runs one task, ten, fifty, or the full pinned
dev set, because the point of the staging is to fix infrastructure before spending
on scale, not to use different code at each size.

    # rehearse the whole loop for free
    python scripts/run_spider_benchmark.py --mock --limit 5

    # Step 9: one task, end to end
    python scripts/run_spider_benchmark.py --limit 1 --stage single

    # Step 13: smoke
    python scripts/run_spider_benchmark.py --limit 10 --stage smoke

    # Step 14: debugging benchmark
    python scripts/run_spider_benchmark.py --limit 50 --sample --stage debug

    # Step 15: the full pinned dev set
    python scripts/run_spider_benchmark.py --stage full

Resumes by default: a rerun with the same `--run-id` skips tasks already persisted
in `episodes.jsonl`, so a failure halfway never means paying twice.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

from backend.app.spider.adapter import ADAPTER_VERSION, build_task_set  # noqa: E402
from backend.app.spider.agent import (  # noqa: E402
    AGENT_VERSION,
    MODEL_PRICING,
    AgentConfig,
    SpiderSQLAgent,
)
from backend.app.spider.mock_client import MockOpenAIClient  # noqa: E402
from backend.app.spider.tools import (  # noqa: E402
    MAX_VISIBLE_ROWS,
    TOOL_SCHEMA_VERSION,
)
from backend.app.spider.trajectory import (  # noqa: E402
    DEFAULT_RUN_ROOT,
    HALTING_TERMINATIONS,
    TerminationReason,
    TrajectoryStore,
)
from backend.app.tracing import (  # noqa: E402
    SERVICE_LAYER_GATEWAY,
    configure_tracing,
    current_trace_id,
    force_flush_traces,
    get_tracer,
)
from opentelemetry import context as otel_context  # noqa: E402
from opentelemetry.trace import set_span_in_context  # noqa: E402

# Fixed so `--sample` selects the same tasks on every run. A benchmark whose task
# subset changes between runs cannot support a regression comparison.
SAMPLE_SEED = 20260812


def git_commit_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def git_is_dirty() -> bool:
    try:
        output = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return bool(output.strip())
    except Exception:  # noqa: BLE001
        return False


def build_client(model: str, mock: bool, answers: dict[str, str] | None):
    if mock:
        return MockOpenAIClient(answers=answers)

    from openai import OpenAI

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit(
            "OPENAI_API_KEY is not set. Set it in .env, or pass --mock to rehearse."
        )
    # max_retries=0 is deliberate. The SDK's default retry silently re-sends on
    # 429, which turns an exhausted quota into what looks like provider latency:
    # a 5-token call measured 18s that was really two hidden retries. Retries are
    # handled explicitly in the agent, where they can be classified and recorded.
    return OpenAI(api_key=api_key, max_retries=0)


def select_tasks(task_set, limit: int | None, sample: bool, task_ids: list[str] | None):
    tasks = list(task_set)

    if task_ids:
        wanted = set(task_ids)
        selected = [task for task in tasks if task.task_id in wanted]
        missing = wanted - {task.task_id for task in selected}
        if missing:
            raise SystemExit(f"Unknown task IDs: {sorted(missing)}")
        return selected

    if limit is None:
        return tasks

    if sample:
        # Stratified by database so a 50-task debug run touches many schemas
        # rather than 50 questions over one table.
        by_database: dict[str, list] = {}
        for task in tasks:
            by_database.setdefault(task.database_id, []).append(task)

        rng = random.Random(SAMPLE_SEED)
        for group in by_database.values():
            rng.shuffle(group)

        selected = []
        databases = sorted(by_database)
        index = 0
        while len(selected) < limit:
            progressed = False
            for database_id in databases:
                group = by_database[database_id]
                if index < len(group):
                    selected.append(group[index])
                    progressed = True
                    if len(selected) >= limit:
                        break
            if not progressed:
                break
            index += 1
        return sorted(selected, key=lambda task: task.task_id)

    return tasks[:limit]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", default="dev")
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--prompt-version", default="sql_agent_v1")
    parser.add_argument("--max-steps", type=int, default=10)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--sample",
        action="store_true",
        help="Select --limit tasks stratified across databases (seeded, reproducible).",
    )
    parser.add_argument("--task-id", action="append", dest="task_ids")
    parser.add_argument("--run-id", default=None)
    parser.add_argument(
        "--stage",
        default="adhoc",
        choices=["single", "smoke", "debug", "full", "adhoc"],
        help="Recorded in the run config so staged runs are distinguishable.",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Rehearse with a scripted client. Never a measured result.",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Re-run tasks already persisted under this run ID.",
    )
    parser.add_argument("--workspace", default=None, help="Where episode DB copies go.")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help=(
            "Episodes to run in parallel. Episodes are independent - each gets its "
            "own database copy and its own conversation - so concurrency changes "
            "wall time, not per-episode behaviour. Recorded in the run config. "
            "Default 1 preserves the sequential mode the P0 baseline used."
        ),
    )
    parser.add_argument(
        "--empty-result-policy",
        default="baseline",
        choices=["baseline", "accept_empty"],
        help=(
            "P2 Intervention A. 'baseline' reproduces prior runs byte-for-byte; "
            "'accept_empty' labels execution outcomes explicitly and stops an "
            "empty result reading as evidence of wrong SQL. Recorded in the run "
            "config so control and treatment share one commit."
        ),
    )
    parser.add_argument(
        "--disable-tool-validation",
        action="store_true",
        help=(
            "ABLATION: revert inspect_schema to silently ignoring unknown "
            "arguments (the spider_tools_v1 defect). Recorded under a distinct "
            "tool_schema_version so it cannot be confused with a normal run."
        ),
    )
    parser.add_argument(
        "--trace-console",
        action="store_true",
        help="Print every span to stdout. Off by default: a full run emits ~10k spans.",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    if args.mock and args.stage == "full":
        raise SystemExit("Refusing to record a mock run as the full benchmark.")

    if not args.trace_console:
        os.environ.setdefault("OTEL_CONSOLE_EXPORTER", "false")
    configure_tracing()
    task_set = build_task_set(args.split)
    tasks = select_tasks(task_set, args.limit, args.sample, args.task_ids)

    prefix = "mockrehearsal" if args.mock else f"spider_{args.stage}"
    run_id = args.run_id or f"{prefix}__{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    store = TrajectoryStore(run_id)

    if args.no_resume:
        # The store is append-only, so re-running without clearing would leave two
        # episodes per task and silently double-count them in every metric.
        store.reset()
        already_done: set[str] = set()
        pruned = 0
    else:
        # Episodes that ended for an infrastructure reason measured nothing. They
        # are removed so this session re-runs them and the file does not end up
        # with two rows for one task.
        pruned = store.prune_infrastructure_episodes()
        already_done = store.completed_task_ids()

    pending = [task for task in tasks if task.task_id not in already_done]

    answers = None
    if args.mock:
        # Half the rehearsal tasks get the gold query so SUCCESS and
        # VERIFICATION_FAILED are both exercised. Gold never reaches the agent's
        # own channel - the mock client is not the system under test.
        answers = {
            task.question: task.gold_query
            for index, task in enumerate(pending)
            if index % 2 == 0
        }

    agent_config = AgentConfig(
        model=args.model,
        prompt_version=args.prompt_version,
        max_steps=args.max_steps,
        temperature=args.temperature,
        validate_tool_arguments_enabled=not args.disable_tool_validation,
        empty_result_policy=args.empty_result_policy,
    )
    effective_tool_schema = (
        TOOL_SCHEMA_VERSION
        if agent_config.validate_tool_arguments_enabled
        else f"{TOOL_SCHEMA_VERSION}__validation_off_ablation"
    )
    client = build_client(args.model, args.mock, answers)
    agent = SpiderSQLAgent(client=client, config=agent_config)

    configuration = {
        "run_id": run_id,
        "stage": args.stage,
        "is_mock": args.mock,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "agent_version": AGENT_VERSION,
        "prompt_version": args.prompt_version,
        "tool_schema_version": effective_tool_schema,
        "tool_argument_validation": agent_config.validate_tool_arguments_enabled,
        "empty_result_policy": agent_config.empty_result_policy,
        "adapter_version": ADAPTER_VERSION,
        "top_p": agent_config.top_p,
        "seed": agent_config.seed,
        "model_version": args.model,
        "model_pricing_usd_per_1m": MODEL_PRICING.get(args.model),
        "max_steps": args.max_steps,
        "temperature": args.temperature,
        "max_visible_rows": MAX_VISIBLE_ROWS,
        "concurrency": args.concurrency,
        "selected_task_count": len(tasks),
        "selected_task_ids": [task.task_id for task in tasks],
        "sampled": args.sample,
        "sample_seed": SAMPLE_SEED if args.sample else None,
        "code_commit_sha": git_commit_sha(),
        "code_working_tree_dirty": git_is_dirty(),
        **task_set.configuration(),
    }
    store.write_config(configuration)

    label = "MOCK REHEARSAL" if args.mock else f"stage={args.stage}"
    print(f"Run {run_id} [{label}]")
    print(f"  model            {args.model} (prompt {args.prompt_version}, max_steps {args.max_steps})")
    print(f"  concurrency      {args.concurrency}")
    print(f"  dataset          {task_set.dataset_version}")
    print(f"  valid tasks      {len(task_set):,}  excluded {len(task_set.excluded)}")
    print(f"  selected         {len(tasks):,}  already done {len(already_done):,}  to run {len(pending):,}")
    if pruned:
        print(f"  pruned           {pruned:,} infrastructure-terminated episode(s) "
              f"from a previous session; they will be re-run")
    print(f"  artifacts        {store.run_dir}")
    print()

    if not pending:
        print("Nothing to run.")
        return 0

    tracer = get_tracer()
    counts: dict[str, int] = {}
    passed = 0
    total_cost = 0.0
    started = time.perf_counter()

    with tracer.start_as_current_span("eval.run") as run_span:
        run_span.set_attribute("service.layer", SERVICE_LAYER_GATEWAY)
        run_span.set_attribute("run.id", run_id)
        run_span.set_attribute("dataset.name", "spider")
        run_span.set_attribute("dataset.version", task_set.dataset_version)
        run_span.set_attribute("model.name", args.model)
        run_span.set_attribute("prompt.version", args.prompt_version)
        run_span.set_attribute("tool_schema.version", TOOL_SCHEMA_VERSION)
        run_span.set_attribute("run.task_count", len(pending))
        run_span.set_attribute("run.is_mock", args.mock)
        run_span.set_attribute("run.concurrency", args.concurrency)
        print(f"  trace_id         {current_trace_id()}\n")

        # Worker threads start with an empty OTel context, so an episode span
        # opened there would become a root span and lose its eval.run parent.
        # The run span's context is captured once and re-attached inside each
        # worker, which keeps the trace tree identical to the sequential mode.
        run_context = set_span_in_context(run_span)
        progress_lock = threading.Lock()
        completed = 0
        halt = threading.Event()

        def execute(task):
            if halt.is_set():
                # A halting condition was already hit. Skipping keeps the episode
                # unrecorded so a resume re-runs it, rather than persisting a
                # quota artefact that later analysis would read as a measurement.
                return task, None
            token = otel_context.attach(run_context)
            try:
                return task, agent.run_episode(
                    task=task,
                    run_id=run_id,
                    store=store,
                    dataset_version=task_set.dataset_version,
                    workspace=args.workspace,
                )
            finally:
                otel_context.detach(token)

        def record(task, episode) -> None:
            nonlocal passed, total_cost, completed
            if episode is None:
                return
            if episode.termination_reason in HALTING_TERMINATIONS:
                halt.set()
            with progress_lock:
                completed += 1
                index = completed
                reason = episode.termination_reason.value
                counts[reason] = counts.get(reason, 0) + 1
                total_cost += episode.estimated_cost
                if episode.termination_reason is TerminationReason.SUCCESS:
                    passed += 1
                if not args.quiet:
                    marker = (
                        "PASS"
                        if episode.termination_reason is TerminationReason.SUCCESS
                        else "    "
                    )
                    print(
                        f"  [{index:>4}/{len(pending)}] {marker} {task.task_id} "
                        f"{reason:<20} steps={episode.total_steps:<3} "
                        f"tok={episode.input_tokens + episode.output_tokens:<6} "
                        f"${episode.estimated_cost:.5f}"
                    )

        if args.concurrency <= 1:
            for task in pending:
                if halt.is_set():
                    break
                _, episode = execute(task)
                record(task, episode)
        else:
            with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
                futures = [pool.submit(execute, task) for task in pending]
                for future in as_completed(futures):
                    task, episode = future.result()
                    record(task, episode)

        elapsed = time.perf_counter() - started
        run_span.set_attribute("run.passed", passed)
        run_span.set_attribute("run.elapsed_seconds", elapsed)

    force_flush_traces()

    halted = counts.get(TerminationReason.RATE_LIMITED.value, 0) > 0
    done_now = sum(counts.values())

    print()
    print(f"Ran {done_now:,} episodes in {elapsed / 60:.1f} min")
    print(f"  passed         {passed:,}/{max(done_now, 1):,} "
          f"({passed / max(done_now, 1):.1%})")
    print(f"  estimated cost ${total_cost:.4f} (list price, not billed amount)")
    print(f"  per task       ${total_cost / max(done_now, 1):.5f}")
    print("  terminations:")
    for reason, count in sorted(counts.items(), key=lambda item: -item[1]):
        print(f"    {reason:<22} {count:,}")
    print()
    print(f"Artifacts: {store.run_dir}")
    print(f"Report:    python scripts/report_spider_metrics.py --run-id {run_id}")

    if args.mock:
        print("\nThis was a MOCK rehearsal. It is not a measured result.")

    if halted:
        remaining = len(pending) - done_now
        print()
        print("=" * 68)
        print("HALTED: provider rate limit / quota exhausted.")
        print(f"  episodes completed this session : {done_now:,}")
        print(f"  episodes still outstanding      : {remaining:,}")
        print("  Completed episodes are checkpointed. Re-run the SAME command in")
        print("  the next quota window; it resumes from episodes.jsonl and will")
        print("  not re-run or re-pay for anything already recorded:")
        print(f"    python scripts/run_spider_benchmark.py --stage {args.stage} "
              f"--run-id {run_id} --concurrency {args.concurrency}")
        print("  This run is INCOMPLETE and must not be scored until it finishes.")
        print("=" * 68)
        # Distinct from 1 so a wrapper can tell "quota, come back later" apart
        # from "the run failed".
        return 75

    return 0


if __name__ == "__main__":
    sys.exit(main())
