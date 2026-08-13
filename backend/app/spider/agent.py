"""The minimal LangGraph SQL agent under test.

    START -> model -> tool call? -- yes --> tool --> model
                        |
                        no
                        v
                      finish -> END

The graph is deliberately three nodes. The point of P0 is not a clever agent; it
is that the *system under test is genuinely an agent* - it chooses whether to look
at the schema, whether to test a query, and when it is done - so that the platform
measures tool-use behaviour rather than one templated generation.

Instrumentation is written alongside the nodes rather than bolted on afterwards
(plan, Step 11), so a step that exists in the trajectory always has a span and
vice versa. `scripts/report_spider_metrics.py` checks that correspondence and
reports any disagreement as an infrastructure failure.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from backend.app.spider.environment import EpisodeDatabase
from backend.app.spider.evaluator import VerificationOutcome, verify_sql
from backend.app.spider.loader import SQLTask
from backend.app.spider.tools import (
    MAX_VISIBLE_ROWS,
    TOOL_SCHEMA_VERSION,
    TOOL_SPECS,
    ToolResult,
    execute_sql,
    inspect_schema,
    validate_tool_arguments,
)
from backend.app.spider.trajectory import (
    AgentEpisode,
    AgentStep,
    StepType,
    TerminationReason,
    TrajectoryStore,
)
from backend.app.tracing import (
    SERVICE_LAYER_JUDGE,
    SERVICE_LAYER_PROVIDER,
    SERVICE_LAYER_STORAGE,
    SERVICE_LAYER_TOOL,
    current_trace_id,
    get_tracer,
)

# Published list prices, USD per 1M tokens. Cost is therefore an *estimate from
# list price*, not a measured invoice; the metrics report says so explicitly.
MODEL_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o-mini": {"input": 0.15, "cached_input": 0.075, "output": 0.60},
    "gpt-4o": {"input": 2.50, "cached_input": 1.25, "output": 10.00},
    "gpt-4.1-mini": {"input": 0.40, "cached_input": 0.10, "output": 1.60},
}

# The system prompt is a measured input. Changing its wording changes results, so
# it is versioned and the version is persisted on every episode.
SQL_AGENT_PROMPTS: dict[str, str] = {
    "sql_agent_v1": (
        "You are a SQL analyst answering questions against a SQLite database.\n"
        "\n"
        "You do not know the schema. Discover it with the inspect_schema tool: call "
        "it with no arguments to list tables, then call it with a table name to see "
        "that table's columns, primary key, and foreign keys.\n"
        "\n"
        "Use execute_sql to run a candidate SELECT and check that it works and "
        "returns what you expect. The database is read-only.\n"
        "\n"
        "When you are confident, call submit_answer with the final SQL query. Submit "
        "exactly one SELECT statement that answers the question. Do not explain it.\n"
        "\n"
        "Guidance:\n"
        "- Inspect the schema before writing SQL. Column names are often not what "
        "you would guess.\n"
        "- Prefer testing a query with execute_sql before submitting it.\n"
        "- Return exactly the columns the question asks for, no more."
    ),
}

DEFAULT_PROMPT_VERSION = "sql_agent_v1"
AGENT_VERSION = "spider_langgraph_agent_v1"


class SQLAgentError(Exception):
    pass


@dataclass
class AgentConfig:
    model: str = "gpt-4o-mini"
    prompt_version: str = DEFAULT_PROMPT_VERSION
    # Maximum *model* turns. Tool calls are not counted against it, because the
    # budget that matters is how many times the agent gets to think, and counting
    # tools would make the cap depend on how chatty the tool schema is.
    max_steps: int = 10
    temperature: float = 0.0
    # Sampling controls are recorded explicitly, including when they are NOT sent.
    # `None` means the parameter is omitted from the request and the provider
    # default applies. Without recording that, "identical configuration" cannot be
    # checked - a reader cannot tell an unset parameter from one never considered.
    #
    # OpenAI's `seed` is best-effort, not a determinism guarantee, so runs are
    # described as "repeated under identical recorded configuration", never as
    # seeded.
    top_p: float | None = None
    seed: int | None = None
    max_completion_tokens: int = 800
    # Transient API failures are retried; a persistent one terminates the episode
    # as MODEL_ERROR and is reported as an infrastructure failure, never as a
    # wrong answer.
    max_model_retries: int = 3
    retry_backoff_seconds: float = 2.0
    request_timeout_seconds: float = 120.0


@dataclass
class EpisodeContext:
    """Per-episode resources handed to graph nodes via LangGraph's config."""

    episode_id: str
    run_id: str
    task: SQLTask
    database: EpisodeDatabase
    store: TrajectoryStore
    config: AgentConfig
    client: Any
    steps: list[AgentStep] = field(default_factory=list)
    counters: dict[str, int] = field(default_factory=dict)

    def bump(self, key: str, amount: int = 1) -> None:
        self.counters[key] = self.counters.get(key, 0) + amount


def _keep_last(_current: Any, new: Any) -> Any:
    """State reducer: nodes return the full value they computed."""
    return new


class AgentState(TypedDict):
    """Deliberately small (plan, Step 7).

    No memory, tenant state, lease state, fencing, or durable intent logging.
    Those are P3-P5 concerns and adding fields for them now would make this
    benchmark measure a system that does not exist yet.
    """

    task_id: str
    question: str
    messages: Annotated[list[dict[str, Any]], _keep_last]
    tool_calls: Annotated[list[dict[str, Any]], _keep_last]
    step_index: Annotated[int, _keep_last]
    model_step_count: Annotated[int, _keep_last]

    final_sql: str | None
    termination_reason: str | None

    input_tokens: Annotated[int, _keep_last]
    output_tokens: Annotated[int, _keep_last]
    estimated_cost: Annotated[float, _keep_last]


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
) -> float:
    pricing = MODEL_PRICING.get(model)
    if pricing is None:
        # Unknown model: report zero rather than guess. A wrong price silently
        # propagates into every cost-per-task figure.
        return 0.0

    uncached = max(input_tokens - cached_input_tokens, 0)
    return (
        uncached * pricing["input"]
        + cached_input_tokens * pricing.get("cached_input", pricing["input"])
        + output_tokens * pricing["output"]
    ) / 1_000_000


def _context_from(config: RunnableConfig) -> EpisodeContext:
    context = (config or {}).get("configurable", {}).get("episode_context")
    if context is None:
        raise SQLAgentError("episode_context missing from graph config")
    return context


def _payload_ref(episode_id: str, step_index: int, kind: str) -> str:
    return f"{episode_id}:{step_index:03d}:{kind}"


def _model_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    context = _context_from(config)
    agent_config = context.config
    tracer = get_tracer()

    step_index = state["step_index"]
    messages = state["messages"]

    with tracer.start_as_current_span("agent.model_step") as span:
        span.set_attribute("service.layer", SERVICE_LAYER_PROVIDER)
        span.set_attribute("run.id", context.run_id)
        span.set_attribute("episode.id", context.episode_id)
        span.set_attribute("task.id", context.task.task_id)
        span.set_attribute("model.name", agent_config.model)
        span.set_attribute("prompt.version", agent_config.prompt_version)
        span.set_attribute("tool_schema.version", TOOL_SCHEMA_VERSION)
        span.set_attribute("agent.step_index", step_index)

        started = time.perf_counter()
        last_error: Exception | None = None
        response = None

        for attempt in range(agent_config.max_model_retries):
            try:
                optional: dict[str, Any] = {}
                if agent_config.top_p is not None:
                    optional["top_p"] = agent_config.top_p
                if agent_config.seed is not None:
                    optional["seed"] = agent_config.seed

                response = context.client.chat.completions.create(
                    model=agent_config.model,
                    messages=messages,
                    tools=TOOL_SPECS,
                    tool_choice="auto",
                    **optional,
                    # One tool call per turn. Parallel calls would make step
                    # accounting ambiguous and let the agent submit an answer in
                    # the same turn it inspects the schema.
                    parallel_tool_calls=False,
                    temperature=agent_config.temperature,
                    max_tokens=agent_config.max_completion_tokens,
                    timeout=agent_config.request_timeout_seconds,
                )
                break
            except Exception as error:  # noqa: BLE001 - retried, then reported
                last_error = error
                if attempt < agent_config.max_model_retries - 1:
                    time.sleep(agent_config.retry_backoff_seconds * (2**attempt))

        latency_ms = (time.perf_counter() - started) * 1000.0

        if response is None:
            span.set_attribute("model.error", str(last_error))
            span.set_attribute("termination.reason", TerminationReason.MODEL_ERROR.value)
            context.steps.append(
                AgentStep(
                    episode_id=context.episode_id,
                    step_index=step_index,
                    step_type=StepType.MODEL,
                    latency_ms=latency_ms,
                    trace_id=current_trace_id(),
                )
            )
            return {
                "step_index": step_index + 1,
                "model_step_count": state["model_step_count"] + 1,
                "termination_reason": TerminationReason.MODEL_ERROR.value,
                "messages": messages,
            }

        # The alias `gpt-4o-mini` resolves to a dated revision that the provider
        # can change under us. Capturing what actually answered is the only way a
        # later run can be compared honestly against this one.
        model_revision = getattr(response, "model", None) or ""
        system_fingerprint = getattr(response, "system_fingerprint", None) or ""

        usage = response.usage
        input_tokens = getattr(usage, "prompt_tokens", 0) or 0
        output_tokens = getattr(usage, "completion_tokens", 0) or 0
        cached_tokens = 0
        details = getattr(usage, "prompt_tokens_details", None)
        if details is not None:
            cached_tokens = getattr(details, "cached_tokens", 0) or 0

        step_cost = estimate_cost(
            agent_config.model, input_tokens, output_tokens, cached_tokens
        )

        choice = response.choices[0]
        message = choice.message
        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": message.content,
        }
        raw_tool_calls = message.tool_calls or []
        if raw_tool_calls:
            assistant_message["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in raw_tool_calls
            ]

        input_ref = context.store.store_payload(
            _payload_ref(context.episode_id, step_index, "model_input"),
            "model_input",
            messages,
        )
        output_ref = context.store.store_payload(
            _payload_ref(context.episode_id, step_index, "model_output"),
            "model_output",
            assistant_message,
        )

        span.set_attribute("input_tokens", input_tokens)
        span.set_attribute("output_tokens", output_tokens)
        span.set_attribute("cached_input_tokens", cached_tokens)
        span.set_attribute("finish_reason", choice.finish_reason or "")
        span.set_attribute("model.tool_call_count", len(raw_tool_calls))
        span.set_attribute("model.revision", model_revision)

        context.steps.append(
            AgentStep(
                episode_id=context.episode_id,
                step_index=step_index,
                step_type=StepType.MODEL,
                model_input_ref=input_ref,
                model_output_ref=output_ref,
                input_tokens=input_tokens,
                cached_input_tokens=cached_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                estimated_cost=step_cost,
                model_revision=model_revision,
                system_fingerprint=system_fingerprint,
                trace_id=current_trace_id(),
            )
        )

    pending = [
        {
            "id": call.id,
            "name": call.function.name,
            "arguments": call.function.arguments,
        }
        for call in raw_tool_calls
    ]

    update: dict[str, Any] = {
        "messages": messages + [assistant_message],
        "tool_calls": pending,
        "step_index": step_index + 1,
        "model_step_count": state["model_step_count"] + 1,
        "input_tokens": state["input_tokens"] + input_tokens,
        "output_tokens": state["output_tokens"] + output_tokens,
        "estimated_cost": state["estimated_cost"] + step_cost,
    }

    if not pending:
        # The model stopped without calling a tool and without submitting. That is
        # a real agent failure mode, distinct from running out of steps.
        update["termination_reason"] = TerminationReason.NO_FINAL_SQL.value

    return update


def _run_tool(context: EpisodeContext, name: str, arguments: dict[str, Any]) -> ToolResult:
    """Dispatch one tool call inside its own span.

    The span is opened **before** argument validation. An earlier version
    validated first and returned early, so a rejected call produced a trajectory
    step with no span at all — measured on run `spider_full__p0_v1` as 23
    `inspect_schema` records against 2,831 spans for 2,854 calls. That silently
    broke the invariant this module claims: every tool step has a span.
    """
    if name not in {"inspect_schema", "execute_sql"}:
        raise SQLAgentError(f"Unknown tool {name!r}")

    tracer = get_tracer()

    with tracer.start_as_current_span(f"tool.{name}") as span:
        span.set_attribute("service.layer", SERVICE_LAYER_TOOL)
        span.set_attribute("tool.name", name)
        span.set_attribute("run.id", context.run_id)
        span.set_attribute("episode.id", context.episode_id)
        span.set_attribute("task.id", context.task.task_id)

        argument_error = validate_tool_arguments(name, arguments)
        if argument_error:
            # A normal failed tool result, not an exception: a wrong argument name
            # is the model's mistake and it can fix it on the next turn.
            #
            # full_result is set explicitly. Letting it default to {} wrote an
            # empty payload, so the rejection reason was missing from the audit
            # trail — 23 of 23 rejected calls in `spider_full__p0_v1`.
            span.set_attribute("tool.success", False)
            span.set_attribute("tool.rejected_arguments", True)
            span.set_attribute("tool.error", argument_error)
            return ToolResult(
                tool_name=name,
                success=False,
                model_visible={"error": argument_error},
                full_result={"error": argument_error, "arguments": arguments},
                error=argument_error,
            )

        if name == "inspect_schema":
            table_name = arguments.get("table_name")
            span.set_attribute("tool.table_name", table_name or "")
            result = inspect_schema(context.database, table_name)
        else:
            with tracer.start_as_current_span("sqlite.query") as query_span:
                query_span.set_attribute("service.layer", SERVICE_LAYER_STORAGE)
                # run.id and episode.id go on *every* span, including the nested
                # ones. Without them a run-scoped trace query silently returns a
                # subset, which reads as missing instrumentation.
                query_span.set_attribute("run.id", context.run_id)
                query_span.set_attribute("episode.id", context.episode_id)
                query_span.set_attribute("db.system", "sqlite")
                query_span.set_attribute("db.name", context.task.database_id)
                result = execute_sql(context.database, arguments.get("query", ""))
                query_span.set_attribute(
                    "db.row_count", result.full_result.get("row_count", 0)
                )
                query_span.set_attribute("db.success", result.success)

        span.set_attribute("tool.success", result.success)
        span.set_attribute("tool.latency_ms", result.latency_ms)
        return result


def _tool_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    context = _context_from(config)
    messages = list(state["messages"])
    step_index = state["step_index"]
    final_sql = state.get("final_sql")
    termination: str | None = None

    for call in state["tool_calls"]:
        name = call["name"]
        try:
            arguments = json.loads(call["arguments"] or "{}")
            if not isinstance(arguments, dict):
                raise ValueError("tool arguments must be a JSON object")
        except (json.JSONDecodeError, ValueError) as error:
            # Malformed arguments are the model's mistake, so they come back as a
            # tool message it can correct rather than a TOOL_ERROR. Only the
            # platform's own failures count as infrastructure failures.
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(
                        {"error": f"Could not parse arguments: {error}"}
                    ),
                }
            )
            context.steps.append(
                AgentStep(
                    episode_id=context.episode_id,
                    step_index=step_index,
                    step_type=StepType.TOOL,
                    tool_name=name,
                    tool_success=False,
                    trace_id=current_trace_id(),
                )
            )
            step_index += 1
            continue

        if name == "submit_answer":
            # Instrumented like any other tool. It previously had no span at all -
            # 986 trajectory records against 0 spans in `spider_full__p0_v1` -
            # because it is handled here rather than in `_run_tool`. Being a
            # terminal state transition is not a reason to be invisible in a trace.
            with get_tracer().start_as_current_span("tool.submit_answer") as span:
                span.set_attribute("service.layer", SERVICE_LAYER_TOOL)
                span.set_attribute("tool.name", name)
                span.set_attribute("run.id", context.run_id)
                span.set_attribute("episode.id", context.episode_id)
                span.set_attribute("task.id", context.task.task_id)
                argument_error = validate_tool_arguments(name, arguments)
                span.set_attribute("tool.success", not argument_error)
                if argument_error:
                    span.set_attribute("tool.error", argument_error)

            if argument_error:
                # Without this, `submit_answer({"sql": ...})` would set no final
                # SQL and the episode would be recorded as NO_FINAL_SQL - scoring
                # a naming slip as if the agent never produced an answer.
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": json.dumps({"error": argument_error}),
                    }
                )
                context.steps.append(
                    AgentStep(
                        episode_id=context.episode_id,
                        step_index=step_index,
                        step_type=StepType.TOOL,
                        tool_name=name,
                        tool_args=arguments,
                        tool_success=False,
                        trace_id=current_trace_id(),
                    )
                )
                step_index += 1
                continue

            final_sql = (arguments.get("query") or "").strip() or None
            ref = context.store.store_payload(
                _payload_ref(context.episode_id, step_index, "submit_answer"),
                "submit_answer",
                arguments,
            )
            context.steps.append(
                AgentStep(
                    episode_id=context.episode_id,
                    step_index=step_index,
                    step_type=StepType.TOOL,
                    tool_name=name,
                    tool_args=arguments,
                    tool_result_ref=ref,
                    tool_success=final_sql is not None,
                    trace_id=current_trace_id(),
                )
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps({"submitted": True}),
                }
            )
            step_index += 1
            termination = (
                None if final_sql else TerminationReason.NO_FINAL_SQL.value
            )
            # submit_answer ends the episode; anything after it is ignored.
            break

        try:
            result = _run_tool(context, name, arguments)
        except SQLAgentError as error:
            # An unknown tool name means the tool schema and the dispatcher
            # disagree. That is this platform's bug, so it is TOOL_ERROR.
            context.steps.append(
                AgentStep(
                    episode_id=context.episode_id,
                    step_index=step_index,
                    step_type=StepType.TOOL,
                    tool_name=name,
                    tool_success=False,
                    trace_id=current_trace_id(),
                )
            )
            return {
                "messages": messages,
                "tool_calls": [],
                "step_index": step_index + 1,
                "termination_reason": TerminationReason.TOOL_ERROR.value,
                "final_sql": final_sql,
            }

        if name == "inspect_schema":
            context.bump("schema_inspections")
        elif name == "execute_sql":
            context.bump("sql_executions")
            if not result.success:
                context.bump("sql_execution_errors")

        result_ref = context.store.store_payload(
            _payload_ref(context.episode_id, step_index, "tool_result"),
            "tool_result",
            result.full_result,
        )
        context.steps.append(
            AgentStep(
                episode_id=context.episode_id,
                step_index=step_index,
                step_type=StepType.TOOL,
                tool_name=name,
                tool_args=arguments,
                tool_result_ref=result_ref,
                tool_success=result.success,
                latency_ms=result.latency_ms,
                trace_id=current_trace_id(),
            )
        )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call["id"],
                "content": json.dumps(result.model_visible, default=str),
            }
        )
        step_index += 1

    return {
        "messages": messages,
        "tool_calls": [],
        "step_index": step_index,
        "final_sql": final_sql,
        "termination_reason": termination,
    }


def _route_after_model(state: AgentState) -> str:
    if state.get("termination_reason"):
        return "finish"
    if state.get("final_sql"):
        return "finish"
    if not state["tool_calls"]:
        return "finish"
    return "tool"


def _route_after_tool(state: AgentState, config: RunnableConfig) -> str:
    context = _context_from(config)
    if state.get("final_sql") or state.get("termination_reason"):
        return "finish"
    if state["model_step_count"] >= context.config.max_steps:
        return "max_steps"
    return "model"


def _finish_node(state: AgentState) -> dict[str, Any]:
    return {}


def _max_steps_node(state: AgentState) -> dict[str, Any]:
    return {"termination_reason": TerminationReason.MAX_STEPS.value}


def build_graph():
    """Compile the agent graph. Shape mirrors the P0 plan's Step 8 diagram."""
    graph = StateGraph(AgentState)
    graph.add_node("model", _model_node)
    graph.add_node("tool", _tool_node)
    graph.add_node("finish", _finish_node)
    graph.add_node("max_steps", _max_steps_node)

    graph.add_edge(START, "model")
    graph.add_conditional_edges(
        "model", _route_after_model, {"tool": "tool", "finish": "finish"}
    )
    graph.add_conditional_edges(
        "tool",
        _route_after_tool,
        {"model": "model", "finish": "finish", "max_steps": "max_steps"},
    )
    graph.add_edge("max_steps", "finish")
    graph.add_edge("finish", END)

    return graph.compile()


class SpiderSQLAgent:
    """Runs one Spider task end to end: episode setup, agent, verifier, cleanup."""

    def __init__(self, client: Any, config: AgentConfig | None = None) -> None:
        self.client = client
        self.config = config or AgentConfig()
        if self.config.prompt_version not in SQL_AGENT_PROMPTS:
            raise SQLAgentError(
                f"Unknown prompt_version {self.config.prompt_version!r}. "
                f"Known: {sorted(SQL_AGENT_PROMPTS)}"
            )
        self.graph = build_graph()

    def _initial_messages(self, task: SQLTask) -> list[dict[str, Any]]:
        return [
            {
                "role": "system",
                "content": SQL_AGENT_PROMPTS[self.config.prompt_version],
            },
            {
                "role": "user",
                "content": (
                    f"Database: {task.database_id}\n"
                    f"Question: {task.question}\n\n"
                    "Find the SQL query that answers this question, then call "
                    "submit_answer with it."
                ),
            },
        ]

    def run_episode(
        self,
        task: SQLTask,
        run_id: str,
        store: TrajectoryStore,
        dataset_version: str,
        workspace: str | None = None,
    ) -> AgentEpisode:
        episode_id = uuid.uuid4().hex[:16]
        tracer = get_tracer()
        started = time.perf_counter()

        with tracer.start_as_current_span("agent.episode") as episode_span:
            episode_span.set_attribute("service.layer", SERVICE_LAYER_PROVIDER)
            episode_span.set_attribute("run.id", run_id)
            episode_span.set_attribute("episode.id", episode_id)
            episode_span.set_attribute("task.id", task.task_id)
            episode_span.set_attribute("dataset.name", "spider")
            episode_span.set_attribute("dataset.version", dataset_version)
            episode_span.set_attribute("model.name", self.config.model)
            episode_span.set_attribute("prompt.version", self.config.prompt_version)
            episode_span.set_attribute("tool_schema.version", TOOL_SCHEMA_VERSION)
            episode_span.set_attribute("db.name", task.database_id)
            trace_id = current_trace_id()

            database = EpisodeDatabase(task.database_path, episode_id, workspace)
            context = EpisodeContext(
                episode_id=episode_id,
                run_id=run_id,
                task=task,
                database=database,
                store=store,
                config=self.config,
                client=self.client,
            )

            final_state: dict[str, Any] = {}
            episode_error: str | None = None

            try:
                database.setup()
                initial: AgentState = {
                    "task_id": task.task_id,
                    "question": task.question,
                    "messages": self._initial_messages(task),
                    "tool_calls": [],
                    "step_index": 0,
                    "model_step_count": 0,
                    "final_sql": None,
                    "termination_reason": None,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "estimated_cost": 0.0,
                }
                final_state = self.graph.invoke(
                    initial,
                    config={
                        "configurable": {"episode_context": context},
                        # Guards against a routing bug looping forever. Two graph
                        # nodes per agent step, plus slack for the terminal nodes.
                        "recursion_limit": self.config.max_steps * 2 + 10,
                    },
                )
            except Exception as error:  # noqa: BLE001 - infrastructure failure
                episode_error = f"{type(error).__name__}: {error}"
                final_state = {
                    **(final_state or {}),
                    "termination_reason": TerminationReason.TOOL_ERROR.value,
                }

            final_sql = final_state.get("final_sql")
            termination_raw = final_state.get("termination_reason")

            verification = None
            if episode_error is None:
                verification, termination = self._verify(
                    task, final_sql, termination_raw, database, tracer,
                    run_id=run_id, episode_id=episode_id,
                )
            else:
                termination = TerminationReason.TOOL_ERROR

            episode_span.set_attribute("termination.reason", termination.value)
            episode_span.set_attribute(
                "verification.success", bool(verification and verification.passed)
            )

            try:
                database.cleanup()
            except Exception as error:  # noqa: BLE001
                episode_error = episode_error or f"cleanup failed: {error}"

            for step in context.steps:
                store.record_step(step)

            episode = AgentEpisode(
                episode_id=episode_id,
                run_id=run_id,
                task_id=task.task_id,
                dataset_version=dataset_version,
                model_version=self.config.model,
                prompt_version=self.config.prompt_version,
                tool_schema_version=TOOL_SCHEMA_VERSION,
                status="completed" if episode_error is None else "failed",
                final_sql=final_sql,
                verification_result=(
                    verification.model_dump(mode="json") if verification else None
                ),
                termination_reason=termination,
                total_steps=len(context.steps),
                model_steps=sum(
                    1 for s in context.steps if s.step_type is StepType.MODEL
                ),
                tool_steps=sum(1 for s in context.steps if s.step_type is StepType.TOOL),
                schema_inspections=context.counters.get("schema_inspections", 0),
                sql_executions=context.counters.get("sql_executions", 0),
                sql_execution_errors=context.counters.get("sql_execution_errors", 0),
                input_tokens=sum(s.input_tokens for s in context.steps),
                cached_input_tokens=sum(
                    s.cached_input_tokens for s in context.steps
                ),
                output_tokens=sum(s.output_tokens for s in context.steps),
                estimated_cost=sum(s.estimated_cost for s in context.steps),
                latency_ms=(time.perf_counter() - started) * 1000.0,
                trace_id=trace_id,
                error=episode_error,
            )
            store.record_episode(episode)
            return episode

    def _verify(
        self,
        task: SQLTask,
        final_sql: str | None,
        termination_raw: str | None,
        database: EpisodeDatabase,
        tracer,
        run_id: str,
        episode_id: str,
    ):
        """Verify the final SQL and resolve the termination reason.

        Ordering matters. A termination the agent already earned (MODEL_ERROR,
        MAX_STEPS, NO_FINAL_SQL) is kept even if some SQL exists, so a run that
        ran out of budget is never reported as a plain verification failure.
        """
        if termination_raw in {
            TerminationReason.MODEL_ERROR.value,
            TerminationReason.TOOL_ERROR.value,
        }:
            return None, TerminationReason(termination_raw)

        if not final_sql:
            if termination_raw == TerminationReason.MAX_STEPS.value:
                return None, TerminationReason.MAX_STEPS
            return None, TerminationReason.NO_FINAL_SQL

        # Does the submitted query even run? This is what separates SQL_ERROR from
        # VERIFICATION_FAILED, and the distinction drives which fix comes next.
        sql_runs = True
        try:
            database.execute(final_sql, timeout_seconds=30.0)
        except Exception:  # noqa: BLE001 - a non-executing answer is SQL_ERROR
            sql_runs = False

        with tracer.start_as_current_span("verifier.execution") as span:
            span.set_attribute("service.layer", SERVICE_LAYER_JUDGE)
            span.set_attribute("run.id", run_id)
            span.set_attribute("episode.id", episode_id)
            span.set_attribute("task.id", task.task_id)
            span.set_attribute("db.name", task.database_id)
            verification = verify_sql(
                predicted_sql=final_sql,
                gold_sql=task.gold_query,
                database_path=task.database_path,
                task_id=task.task_id,
                database_id=task.database_id,
            )
            span.set_attribute("verification.success", verification.passed)
            span.set_attribute("verification.outcome", verification.outcome.value)

        if verification.outcome is VerificationOutcome.PASS:
            return verification, TerminationReason.SUCCESS
        if verification.outcome is VerificationOutcome.EVALUATOR_ERROR:
            return verification, TerminationReason.TOOL_ERROR
        if verification.outcome is VerificationOutcome.GOLD_ERROR:
            # Should be impossible: gold-pass QA cleared every task before the run.
            # Surfaced as an infrastructure failure rather than an agent failure.
            return verification, TerminationReason.TOOL_ERROR
        if not sql_runs:
            return verification, TerminationReason.SQL_ERROR
        return verification, TerminationReason.VERIFICATION_FAILED


__all__ = [
    "AGENT_VERSION",
    "AgentConfig",
    "AgentState",
    "MAX_VISIBLE_ROWS",
    "MODEL_PRICING",
    "SQL_AGENT_PROMPTS",
    "SpiderSQLAgent",
    "build_graph",
    "estimate_cost",
]
