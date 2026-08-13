"""The P3 support agent: same LangGraph runtime, effectful tools.

Single agent, as in P0-P2. No multi-agent, no long-term memory, no distributed
execution — those are later phases and adding them here would confound P3's
measurement with an architecture change.

What is new is that tool calls **change the world**, so the trajectory has to
record enough to reconstruct what happened and, in P4, to make each call
individually recoverable:

- a unique `ToolCallIdentity` per call (read and effectful alike, no gaps)
- the arguments as sent, and the structured validation result
- the returned payload or error
- before/after state references and the normalized diff
- the final verifier result

Model turns are capped by a budget derived from the reference trajectories rather
than guessed; see `docs/P3_CONTRACT_V0.md`.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from backend.app.spider.agent import estimate_cost, is_rate_limit_error
from backend.app.spider.trajectory import (
    AgentStep,
    StepType,
    TerminationReason,
    TrajectoryStore,
)
from backend.app.support.environment import SupportEnvironment
from backend.app.support.tools import (
    EFFECTFUL_TOOLS,
    TOOL_SCHEMA_VERSION,
    ToolCallIdentity,
    call_tool,
)
from backend.app.support.verifier import verify
from backend.app.tracing import (
    SERVICE_LAYER_JUDGE,
    SERVICE_LAYER_PROVIDER,
    SERVICE_LAYER_STORAGE,
    SERVICE_LAYER_TOOL,
    current_trace_id,
    get_tracer,
)

AGENT_VERSION = "support_langgraph_agent_v0"
PROMPT_VERSION = "support_agent_v0"

SUPPORT_PROMPTS: dict[str, str] = {
    "support_agent_v0": (
        "You are a support operations agent working on a ticket system.\n"
        "\n"
        "You have read tools (search_tickets, get_ticket, search_policy) and tools "
        "that change state (update_ticket, assign_ticket, add_comment).\n"
        "\n"
        "Rules:\n"
        "- Make ONLY the changes the task requires. Any extra change is a failure, "
        "including comments that were not asked for.\n"
        "- When a task refers to a policy, look it up with search_policy and follow "
        "it exactly rather than guessing.\n"
        "- Reads are free; use them to confirm what you are about to change.\n"
        "- A search that matches nothing is a valid answer, not an error.\n"
        "- Call finish_task when the required changes are done."
    ),
}

TOOL_SPECS: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "search_tickets",
        "description": "Find tickets by status, priority, customer, team, or free text.",
        "parameters": {"type": "object", "properties": {
            "status": {"type": "string"}, "priority": {"type": "string"},
            "customer_id": {"type": "string"}, "team_id": {"type": "string"},
            "customer_name": {"type": "string",
                                   "description": "Case-insensitive substring of the customer name."},
            "query": {"type": "string"}}, "required": []}}},
    {"type": "function", "function": {
        "name": "get_ticket",
        "description": "Full detail for one ticket, with its customer and comments.",
        "parameters": {"type": "object", "properties": {
            "ticket_id": {"type": "string"}}, "required": ["ticket_id"]}}},
    {"type": "function", "function": {
        "name": "search_policy",
        "description": "Search the support policy corpus.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}, "topic": {"type": "string"}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "list_reference_data",
        "description": "List valid team and agent identifiers. Use this before assigning.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "update_ticket",
        "description": "Change a ticket's priority, status, or escalation flag.",
        "parameters": {"type": "object", "properties": {
            "ticket_id": {"type": "string"},
            "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"]},
            "status": {"type": "string", "enum": [
                "open", "in_progress", "waiting_customer", "escalated",
                "resolved", "closed"]},
            "escalated": {"type": "boolean"}}, "required": ["ticket_id"]}}},
    {"type": "function", "function": {
        "name": "assign_ticket",
        "description": "Assign a ticket to a team and/or an agent.",
        "parameters": {"type": "object", "properties": {
            "ticket_id": {"type": "string"}, "team_id": {"type": "string"},
            "assignee_id": {"type": "string"}}, "required": ["ticket_id"]}}},
    {"type": "function", "function": {
        "name": "add_comment",
        "description": "Add a comment to a ticket, optionally with a reason code.",
        "parameters": {"type": "object", "properties": {
            "ticket_id": {"type": "string"}, "body": {"type": "string"},
            "reason_code": {"type": "string"}, "author": {"type": "string"}},
            "required": ["ticket_id", "body"]}}},
    {"type": "function", "function": {
        "name": "finish_task",
        "description": "Declare the required changes complete. Ends the episode.",
        "parameters": {"type": "object", "properties": {
            "summary": {"type": "string"}}, "required": []}}},
]


@dataclass
class SupportAgentConfig:
    model: str = "gpt-4o-mini"
    prompt_version: str = PROMPT_VERSION
    # Derived from the reference-trajectory distribution, not guessed:
    # longest reference is 4 tool calls + 1 finish_task = 5 model turns, and the
    # budget is 2x that. Recomputed and frozen after expansion to ~80 tasks.
    # Frozen at 15 = ceil(2.5 x 6), where 6 is the longest legitimate reference
    # (5 tool calls + finish_task) measured across all 79 references. The worst
    # observed SUCCESSFUL episode used 9 turns, so nothing in the suite is
    # budget-bound. Derivation: docs/P3_BUDGET_DERIVATION.md.
    max_steps: int = 15
    temperature: float = 0.0
    top_p: float | None = None
    seed: int | None = None
    max_completion_tokens: int = 800
    max_model_retries: int = 3
    retry_backoff_seconds: float = 2.0
    retry_on_rate_limit: bool = False
    request_timeout_seconds: float = 120.0
    empty_result_policy: str = "accept_empty"
    # P3 treatment flag, OFF here. Same commit serves control and treatment.
    schema_repair_enabled: bool = False


@dataclass
class SupportEpisodeContext:
    episode_id: str
    run_id: str
    task: Any
    environment: SupportEnvironment
    store: TrajectoryStore
    config: SupportAgentConfig
    client: Any
    steps: list[AgentStep] = field(default_factory=list)
    counters: dict[str, int] = field(default_factory=dict)
    call_index: int = 0
    seen_identities: set[str] = field(default_factory=set)
    model_error: str | None = None

    def bump(self, key: str, amount: int = 1) -> None:
        self.counters[key] = self.counters.get(key, 0) + amount

    def next_identity(self, step_index: int) -> ToolCallIdentity:
        """Allocate the next call identity and enforce uniqueness.

        Uniqueness is asserted rather than assumed: a duplicated identity would
        make a P4 intent log ambiguous about which call it describes, and that is
        exactly the kind of defect that is invisible until it matters.
        """
        identity = ToolCallIdentity(
            episode_id=self.episode_id, step_index=step_index, call_index=self.call_index
        )
        if identity.key() in self.seen_identities:
            raise RuntimeError(f"duplicate tool call identity {identity.key()}")
        self.seen_identities.add(identity.key())
        self.call_index += 1
        return identity


def _keep_last(_current: Any, new: Any) -> Any:
    return new


class SupportAgentState(TypedDict):
    task_id: str
    messages: Annotated[list[dict[str, Any]], _keep_last]
    tool_calls: Annotated[list[dict[str, Any]], _keep_last]
    step_index: Annotated[int, _keep_last]
    model_step_count: Annotated[int, _keep_last]
    finished: bool
    termination_reason: str | None
    input_tokens: Annotated[int, _keep_last]
    output_tokens: Annotated[int, _keep_last]
    estimated_cost: Annotated[float, _keep_last]


def _context(config: RunnableConfig) -> SupportEpisodeContext:
    context = (config or {}).get("configurable", {}).get("episode_context")
    if context is None:
        raise RuntimeError("episode_context missing from graph config")
    return context


def _ref(episode_id: str, step_index: int, kind: str) -> str:
    return f"{episode_id}:{step_index:03d}:{kind}"


def _model_node(state: SupportAgentState, config: RunnableConfig) -> dict[str, Any]:
    context = _context(config)
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
        response, last_error, rate_limited = None, None, False
        api_seconds = wait_seconds = 0.0
        attempts = 0

        for attempt in range(agent_config.max_model_retries):
            attempts = attempt + 1
            call_started = time.perf_counter()
            try:
                optional: dict[str, Any] = {}
                if agent_config.top_p is not None:
                    optional["top_p"] = agent_config.top_p
                if agent_config.seed is not None:
                    optional["seed"] = agent_config.seed
                response = context.client.chat.completions.create(
                    model=agent_config.model, messages=messages, tools=TOOL_SPECS,
                    tool_choice="auto", parallel_tool_calls=False, **optional,
                    temperature=agent_config.temperature,
                    max_tokens=agent_config.max_completion_tokens,
                    timeout=agent_config.request_timeout_seconds,
                )
                api_seconds += time.perf_counter() - call_started
                break
            except Exception as error:  # noqa: BLE001
                api_seconds += time.perf_counter() - call_started
                last_error = error
                if is_rate_limit_error(error) and not agent_config.retry_on_rate_limit:
                    rate_limited = True
                    break
                if attempt < agent_config.max_model_retries - 1:
                    pause = agent_config.retry_backoff_seconds * (2**attempt)
                    wait_started = time.perf_counter()
                    time.sleep(pause)
                    wait_seconds += time.perf_counter() - wait_started

        latency_ms = (time.perf_counter() - started) * 1000.0

        if response is None:
            detail = f"{type(last_error).__name__}: {last_error}"
            reason = (
                TerminationReason.RATE_LIMITED if rate_limited
                else TerminationReason.MODEL_ERROR
            )
            context.model_error = detail
            span.set_attribute("model.error", detail)
            span.set_attribute("termination.reason", reason.value)
            error_ref = context.store.store_payload(
                _ref(context.episode_id, step_index, "model_error"), "model_error",
                {"error": str(last_error), "rate_limited": rate_limited,
                 "attempts": attempts},
            )
            context.steps.append(AgentStep(
                episode_id=context.episode_id, step_index=step_index,
                step_type=StepType.MODEL, model_output_ref=error_ref,
                latency_ms=latency_ms, api_latency_ms=api_seconds * 1000.0,
                retry_wait_ms=wait_seconds * 1000.0, retry_attempts=attempts,
                trace_id=current_trace_id(),
            ))
            return {
                "step_index": step_index + 1,
                "model_step_count": state["model_step_count"] + 1,
                "termination_reason": reason.value, "messages": messages,
            }

        usage = response.usage
        input_tokens = getattr(usage, "prompt_tokens", 0) or 0
        output_tokens = getattr(usage, "completion_tokens", 0) or 0
        details = getattr(usage, "prompt_tokens_details", None)
        cached = getattr(details, "cached_tokens", 0) or 0 if details else 0
        cost = estimate_cost(agent_config.model, input_tokens, output_tokens, cached)

        message = response.choices[0].message
        assistant: dict[str, Any] = {"role": "assistant", "content": message.content}
        raw_calls = message.tool_calls or []
        if raw_calls:
            assistant["tool_calls"] = [
                {"id": c.id, "type": "function",
                 "function": {"name": c.function.name, "arguments": c.function.arguments}}
                for c in raw_calls
            ]

        input_ref = context.store.store_payload(
            _ref(context.episode_id, step_index, "model_input"), "model_input", messages)
        output_ref = context.store.store_payload(
            _ref(context.episode_id, step_index, "model_output"), "model_output", assistant)

        span.set_attribute("input_tokens", input_tokens)
        span.set_attribute("output_tokens", output_tokens)
        span.set_attribute("model.revision", getattr(response, "model", "") or "")

        context.steps.append(AgentStep(
            episode_id=context.episode_id, step_index=step_index,
            step_type=StepType.MODEL, model_input_ref=input_ref,
            model_output_ref=output_ref, input_tokens=input_tokens,
            cached_input_tokens=cached, output_tokens=output_tokens,
            latency_ms=latency_ms, api_latency_ms=api_seconds * 1000.0,
            retry_wait_ms=wait_seconds * 1000.0, retry_attempts=attempts,
            estimated_cost=cost, model_revision=getattr(response, "model", None),
            trace_id=current_trace_id(),
        ))

    pending = [
        {"id": c.id, "name": c.function.name, "arguments": c.function.arguments}
        for c in raw_calls
    ]
    update: dict[str, Any] = {
        "messages": messages + [assistant], "tool_calls": pending,
        "step_index": step_index + 1,
        "model_step_count": state["model_step_count"] + 1,
        "input_tokens": state["input_tokens"] + input_tokens,
        "output_tokens": state["output_tokens"] + output_tokens,
        "estimated_cost": state["estimated_cost"] + cost,
    }
    if not pending:
        update["termination_reason"] = TerminationReason.INCOMPLETE.value
    return update


def _tool_node(state: SupportAgentState, config: RunnableConfig) -> dict[str, Any]:
    context = _context(config)
    tracer = get_tracer()
    messages = list(state["messages"])
    step_index = state["step_index"]
    finished = state.get("finished", False)

    for call in state["tool_calls"]:
        name = call["name"]
        try:
            arguments = json.loads(call["arguments"] or "{}")
            if not isinstance(arguments, dict):
                raise ValueError("arguments must be a JSON object")
            parse_error = None
        except (json.JSONDecodeError, ValueError) as error:
            arguments, parse_error = {}, str(error)

        if name == "finish_task":
            finished = True
            context.steps.append(AgentStep(
                episode_id=context.episode_id, step_index=step_index,
                step_type=StepType.TOOL, tool_name=name, tool_args=arguments,
                tool_success=True, trace_id=current_trace_id(),
            ))
            messages.append({"role": "tool", "tool_call_id": call["id"],
                             "content": json.dumps({"finished": True})})
            step_index += 1
            break

        identity = context.next_identity(step_index)
        with tracer.start_as_current_span(f"tool.{name}") as span:
            span.set_attribute("service.layer", SERVICE_LAYER_TOOL)
            span.set_attribute("run.id", context.run_id)
            span.set_attribute("episode.id", context.episode_id)
            span.set_attribute("tool.name", name)
            span.set_attribute("tool.call_key", identity.key())
            span.set_attribute("tool.effectful", name in EFFECTFUL_TOOLS)

            if parse_error is not None:
                result_payload = {"error_kind": "MALFORMED_ARGUMENTS",
                                  "message": parse_error}
                success, error_kind, mutation = False, "MALFORMED_ARGUMENTS", None
                context.bump("malformed_argument_calls")
            else:
                with tracer.start_as_current_span("support.mutation" if name in EFFECTFUL_TOOLS
                                                  else "support.read") as inner:
                    inner.set_attribute("service.layer", SERVICE_LAYER_STORAGE)
                    inner.set_attribute("run.id", context.run_id)
                    inner.set_attribute("episode.id", context.episode_id)
                    result = call_tool(
                        context.environment, name, arguments, identity,
                        empty_result_policy=context.config.empty_result_policy,
                    )
                result_payload = result.model_visible
                success, error_kind = result.success, result.error_kind
                mutation = result.mutation
                if error_kind == "INVALID_ARGUMENTS":
                    context.bump("invalid_typed_calls")
                if name in EFFECTFUL_TOOLS:
                    context.bump("effectful_calls")
                    if not success:
                        context.bump("effectful_call_failures")
                else:
                    context.bump("read_calls")

            span.set_attribute("tool.success", success)
            if error_kind:
                span.set_attribute("tool.error_kind", error_kind)

        result_ref = context.store.store_payload(
            _ref(context.episode_id, step_index, f"tool_{identity.call_index}"),
            "tool_result",
            {
                "identity": identity.model_dump(),
                "tool": name,
                "tool_schema_version": TOOL_SCHEMA_VERSION,
                "arguments": arguments,
                "raw_arguments": call["arguments"],
                "validation_error": parse_error or (
                    result_payload.get("message") if error_kind == "INVALID_ARGUMENTS" else None
                ),
                "result": result_payload,
                "error_kind": error_kind,
                "effectful": name in EFFECTFUL_TOOLS,
                "mutation": mutation,
            },
        )

        context.steps.append(AgentStep(
            episode_id=context.episode_id, step_index=step_index,
            step_type=StepType.TOOL, tool_name=name, tool_args=arguments,
            tool_result_ref=result_ref, tool_success=success,
            trace_id=current_trace_id(),
        ))
        messages.append({"role": "tool", "tool_call_id": call["id"],
                         "content": json.dumps(result_payload, default=str)})
        step_index += 1

    return {"messages": messages, "tool_calls": [], "step_index": step_index,
            "finished": finished}


def _route_after_model(state: SupportAgentState) -> str:
    if state.get("termination_reason") or not state["tool_calls"]:
        return "finish"
    return "tool"


def _route_after_tool(state: SupportAgentState, config: RunnableConfig) -> str:
    if state.get("finished") or state.get("termination_reason"):
        return "finish"
    if state["model_step_count"] >= _context(config).config.max_steps:
        return "max_steps"
    return "model"


def build_graph():
    graph = StateGraph(SupportAgentState)
    graph.add_node("model", _model_node)
    graph.add_node("tool", _tool_node)
    graph.add_node("finish", lambda state: {})
    graph.add_node("max_steps", lambda state: {
        "termination_reason": TerminationReason.MAX_STEPS.value})
    graph.add_edge(START, "model")
    graph.add_conditional_edges("model", _route_after_model,
                                {"tool": "tool", "finish": "finish"})
    graph.add_conditional_edges("tool", _route_after_tool,
                                {"model": "model", "finish": "finish",
                                 "max_steps": "max_steps"})
    graph.add_edge("max_steps", "finish")
    graph.add_edge("finish", END)
    return graph.compile()
