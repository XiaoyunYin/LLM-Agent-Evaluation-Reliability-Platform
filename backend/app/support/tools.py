"""The six tools the P3 agent is given: three read-only, three effectful.

Read and effectful tools are separated explicitly, because P4 needs to identify
every state-changing call individually for intent logging and idempotency. That
boundary is easier to hold from the start than to retrofit.

Arguments are strongly typed and enum-validated. An invalid call is refused with a
**structured** validation error naming the field and the accepted values — which is
what makes the P3 schema-repair experiment possible: the baseline already returns
a machine-readable reason, so the treatment can be "one bounded repair attempt"
rather than "add error messages".

`search_policy` reuses the project's existing hybrid retrieval rather than
introducing a new one. P3 measures whether the agent *chooses and uses* retrieval
correctly, not whether retrieval is well tuned; retuning it here would confound
the two.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field

from backend.app.support.schema import PRIORITIES, STATUSES

# Contract v0. Calibration-stage, deliberately NOT the frozen-final contract:
# argument schemas, enums, return shapes, empty-result semantics and the error
# payload format may still change during calibration, under the documented rules
# in docs/P3_CONTRACT_V0.md. After the freeze, any agent-visible change to this
# surface is an intervention requiring a bridge run.
TOOL_SCHEMA_VERSION = "support_tools_v1"
CONTRACT_STAGE = "calibration"

# Adopted in P2 and generalized here. In Spider it applied to one tool; in P3 the
# same ambiguity exists on every read that can legitimately match nothing - zero
# tickets, zero policies - so the labelling is applied uniformly rather than per
# tool. ON by default per config/adopted_agent_flags.json: a P3 baseline running
# with it off would benchmark an agent older than the one that exists.
EXECUTION_SUCCESS_NONEMPTY = "SUCCESS_NONEMPTY"
EXECUTION_SUCCESS_EMPTY = "SUCCESS_EMPTY"
EXECUTION_ERROR = "ERROR"

EMPTY_RESULT_GUIDANCE = (
    "The call succeeded and matched nothing. An empty result is a valid outcome "
    "when nothing matches - it is not by itself evidence that the call was wrong. "
    "Re-check the arguments against the task; if they are right, act on the empty "
    "result rather than repeating the same call."
)

# Tools whose success can legitimately be empty. Effectful tools are excluded:
# "updated nothing" is not a successful empty read, it is a failed update.
EMPTY_CAPABLE_TOOLS = ("search_tickets", "search_policy")

# Rows the model sees. Same reasoning as P0: the full result is persisted, the
# model's context is not a function of how much data a query happened to match.
MAX_VISIBLE_ROWS = 20

READ_ONLY_TOOLS = ("search_tickets", "get_ticket", "search_policy", "list_reference_data")
EFFECTFUL_TOOLS = ("update_ticket", "assign_ticket", "add_comment")


class ToolCallIdentity(BaseModel):
    """Unique identity for one tool call inside one episode.

    Added now rather than in P4, because P4's write-ahead intent log, idempotency
    keys and fencing all need to name an individual call, and an identity cannot
    be retrofitted onto already-persisted trajectories. Applies to read and
    effectful calls alike so the numbering has no gaps.
    """

    episode_id: str
    step_index: int
    call_index: int

    def key(self) -> str:
        return f"{self.episode_id}:{self.step_index:03d}:{self.call_index:03d}"


class ToolResult(BaseModel):
    tool_name: str
    tool_schema_version: str = TOOL_SCHEMA_VERSION
    identity: ToolCallIdentity | None = None
    success: bool
    effectful: bool
    model_visible: dict[str, Any]
    full_result: dict[str, Any] = Field(default_factory=dict)
    latency_ms: float = 0.0
    error: str | None = None
    error_kind: str | None = None
    # Set for effectful calls that actually changed something, so P4 can identify
    # them without re-deriving from the diff.
    mutation: dict[str, Any] | None = None


class ValidationFailure(Exception):
    """Structured argument rejection: names the field and what was expected."""

    def __init__(self, field: str, message: str, accepted: list[str] | None = None) -> None:
        super().__init__(message)
        self.field = field
        self.message = message
        self.accepted = accepted or []

    def as_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "error_kind": "INVALID_ARGUMENTS",
            "field": self.field,
            "message": self.message,
        }
        if self.accepted:
            payload["accepted_values"] = self.accepted
        return payload


def _require(arguments: dict[str, Any], field: str) -> Any:
    value = arguments.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValidationFailure(field, f"{field} is required")
    return value


def _require_enum(arguments: dict[str, Any], field: str, accepted: tuple[str, ...]) -> str:
    value = _require(arguments, field)
    if value not in accepted:
        raise ValidationFailure(
            field, f"{value!r} is not a valid {field}", list(accepted)
        )
    return value


def _unknown_arguments(arguments: dict[str, Any], accepted: set[str]) -> None:
    unknown = sorted(set(arguments) - accepted)
    if unknown:
        raise ValidationFailure(
            unknown[0],
            f"unknown argument(s) {unknown}",
            sorted(accepted),
        )


def _finish(
    name: str, started: float, visible: dict, *, full=None,
    error=None, error_kind=None, mutation=None,
) -> ToolResult:
    return ToolResult(
        tool_name=name,
        success=error is None,
        effectful=name in EFFECTFUL_TOOLS,
        model_visible=visible,
        full_result=full if full is not None else visible,
        latency_ms=(time.perf_counter() - started) * 1000.0,
        error=error,
        error_kind=error_kind,
        mutation=mutation,
    )


# ---------------------------------------------------------------- read-only


def search_tickets(environment, arguments: dict[str, Any]) -> ToolResult:
    started = time.perf_counter()
    try:
        _unknown_arguments(
            arguments,
            {"status", "priority", "customer_id", "customer_name", "team_id", "query"},
        )
        clauses, params = [], []
        for field in ("status", "priority", "customer_id", "team_id"):
            if arguments.get(field) is not None:
                if field == "status":
                    _require_enum(arguments, "status", STATUSES)
                if field == "priority":
                    _require_enum(arguments, "priority", PRIORITIES)
                clauses.append(f"{field} = ?")
                params.append(arguments[field])
        if arguments.get("customer_id"):
            # A customer_id that matches nothing is refused rather than answered
            # with an empty result. Measured in calibration: the agent passed the
            # customer NAME into customer_id, got zero rows, correctly concluded
            # no such ticket existed, and stopped. That is the same
            # silently-wrong-answer class as the P0 inspect_schema defect - the
            # tool accepted something wrong and returned a plausible answer.
            known = environment.connect().execute(
                "SELECT 1 FROM customers WHERE customer_id = ?",
                (arguments["customer_id"],),
            ).fetchone()
            if known is None:
                raise ValidationFailure(
                    "customer_id",
                    f"no customer with id {arguments['customer_id']!r}; "
                    "if you have the customer's NAME, use customer_name instead",
                    ["customer_name"],
                )

        if arguments.get("customer_name"):
            # Calibration fix: tasks name the customer, and without this the only
            # route from a name to a ticket was guessing the id. Measured on the
            # first calibration run as every lookup_update episode returning zero
            # rows and correctly giving up.
            clauses.append(
                "customer_id IN (SELECT customer_id FROM customers WHERE name = ?)"
            )
            params.append(arguments["customer_name"])
        if arguments.get("query"):
            clauses.append("(subject LIKE ? OR body LIKE ?)")
            params += [f"%{arguments['query']}%"] * 2

        sql = "SELECT ticket_id, customer_id, subject, priority, status, team_id, assignee_id, escalated FROM tickets"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY ticket_id"

        rows = [dict(r) for r in environment.connect().execute(sql, params)]
    except ValidationFailure as failure:
        return _finish("search_tickets", started, failure.as_payload(),
                       error=failure.message, error_kind="INVALID_ARGUMENTS")

    visible = {"tickets": rows[:MAX_VISIBLE_ROWS], "row_count": len(rows)}
    if len(rows) > MAX_VISIBLE_ROWS:
        visible["truncated"] = True
    return _finish("search_tickets", started, visible,
                   full={"tickets": rows, "row_count": len(rows)})


def get_ticket(environment, arguments: dict[str, Any]) -> ToolResult:
    started = time.perf_counter()
    try:
        _unknown_arguments(arguments, {"ticket_id"})
        ticket_id = _require(arguments, "ticket_id")
    except ValidationFailure as failure:
        return _finish("get_ticket", started, failure.as_payload(),
                       error=failure.message, error_kind="INVALID_ARGUMENTS")

    connection = environment.connect()
    row = connection.execute(
        "SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)
    ).fetchone()
    if row is None:
        return _finish(
            "get_ticket", started,
            {"error_kind": "NOT_FOUND", "message": f"no ticket {ticket_id!r}"},
            error=f"no ticket {ticket_id!r}", error_kind="NOT_FOUND",
        )

    ticket = dict(row)
    customer = connection.execute(
        "SELECT * FROM customers WHERE customer_id = ?", (ticket["customer_id"],)
    ).fetchone()
    comments = [
        dict(r) for r in connection.execute(
            "SELECT comment_id, author, reason_code, body FROM comments "
            "WHERE ticket_id = ? ORDER BY created_seq", (ticket_id,)
        )
    ]
    payload = {
        "ticket": ticket,
        "customer": dict(customer) if customer else None,
        "comments": comments,
    }
    return _finish("get_ticket", started, payload)


def search_policy(environment, arguments: dict[str, Any]) -> ToolResult:
    """Policy retrieval.

    Backed by the seeded policy table here. The hybrid pgvector + BM25 + RRF stack
    is the production path and is **not retuned for P3** - what P3 measures is
    whether the agent chooses to retrieve and uses what it gets.
    """
    started = time.perf_counter()
    try:
        _unknown_arguments(arguments, {"query", "topic"})
        query = _require(arguments, "query")
    except ValidationFailure as failure:
        return _finish("search_policy", started, failure.as_payload(),
                       error=failure.message, error_kind="INVALID_ARGUMENTS")

    connection = environment.connect()
    terms = [t for t in str(query).lower().split() if len(t) > 2]
    rows = [dict(r) for r in connection.execute("SELECT * FROM policies ORDER BY policy_id")]
    if arguments.get("topic"):
        rows = [r for r in rows if r["topic"] == arguments["topic"]]

    def score(row: dict) -> int:
        haystack = f"{row['title']} {row['body']} {row['topic']}".lower()
        return sum(1 for term in terms if term in haystack)

    ranked = sorted(rows, key=lambda r: (-score(r), r["policy_id"]))
    hits = [r for r in ranked if score(r) > 0][:5]
    return _finish(
        "search_policy", started,
        {"policies": hits, "row_count": len(hits)},
        full={"policies": ranked, "row_count": len(ranked)},
    )


def list_reference_data(environment, arguments: dict[str, Any]) -> ToolResult:
    """Valid team and agent identifiers.

    Calibration fix. Tasks require assigning to a team, but nothing exposed the
    identifiers, so the agent had to guess: the first calibration run shows it
    trying `team_id="technical"` against a real id of `TEAM-technical`, then
    burning turns searching for the id it could not discover. Guessing an opaque
    identifier is not the capability under test.
    """
    started = time.perf_counter()
    try:
        _unknown_arguments(arguments, set())
    except ValidationFailure as failure:
        return _finish("list_reference_data", started, failure.as_payload(),
                       error=failure.message, error_kind="INVALID_ARGUMENTS")

    connection = environment.connect()
    teams = [dict(r) for r in connection.execute(
        "SELECT team_id, name, queue FROM teams ORDER BY team_id")]
    agents = [dict(r) for r in connection.execute(
        "SELECT agent_id, name, team_id FROM agents WHERE active = 1 ORDER BY agent_id")]
    return _finish("list_reference_data", started,
                   {"teams": teams, "agents": agents,
                    "row_count": len(teams) + len(agents)})


# ---------------------------------------------------------------- effectful


def update_ticket(environment, arguments: dict[str, Any]) -> ToolResult:
    started = time.perf_counter()
    try:
        _unknown_arguments(arguments, {"ticket_id", "priority", "status", "escalated"})
        ticket_id = _require(arguments, "ticket_id")
        updates: dict[str, Any] = {}
        if "priority" in arguments and arguments["priority"] is not None:
            updates["priority"] = _require_enum(arguments, "priority", PRIORITIES)
        if "status" in arguments and arguments["status"] is not None:
            updates["status"] = _require_enum(arguments, "status", STATUSES)
        if "escalated" in arguments and arguments["escalated"] is not None:
            value = arguments["escalated"]
            if not isinstance(value, bool):
                raise ValidationFailure("escalated", "escalated must be true or false",
                                        ["true", "false"])
            updates["escalated"] = 1 if value else 0
        if not updates:
            raise ValidationFailure(
                "priority", "at least one of priority, status, escalated is required",
                ["priority", "status", "escalated"],
            )
    except ValidationFailure as failure:
        return _finish("update_ticket", started, failure.as_payload(),
                       error=failure.message, error_kind="INVALID_ARGUMENTS")

    connection = environment.connect()
    before = connection.execute(
        "SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)
    ).fetchone()
    if before is None:
        return _finish("update_ticket", started,
                       {"error_kind": "NOT_FOUND", "message": f"no ticket {ticket_id!r}"},
                       error=f"no ticket {ticket_id!r}", error_kind="NOT_FOUND")

    assignments = ", ".join(f"{field} = ?" for field in updates)
    connection.execute(
        f"UPDATE tickets SET {assignments} WHERE ticket_id = ?",
        [*updates.values(), ticket_id],
    )
    connection.commit()

    return _finish(
        "update_ticket", started,
        {"updated": True, "ticket_id": ticket_id, "fields": sorted(updates)},
        mutation={"table": "tickets", "key": ticket_id, "fields": updates},
    )


def assign_ticket(environment, arguments: dict[str, Any]) -> ToolResult:
    started = time.perf_counter()
    try:
        _unknown_arguments(arguments, {"ticket_id", "team_id", "assignee_id"})
        ticket_id = _require(arguments, "ticket_id")
        if not arguments.get("team_id") and not arguments.get("assignee_id"):
            raise ValidationFailure(
                "team_id", "one of team_id or assignee_id is required",
                ["team_id", "assignee_id"],
            )
    except ValidationFailure as failure:
        return _finish("assign_ticket", started, failure.as_payload(),
                       error=failure.message, error_kind="INVALID_ARGUMENTS")

    connection = environment.connect()
    if connection.execute("SELECT 1 FROM tickets WHERE ticket_id = ?", (ticket_id,)).fetchone() is None:
        return _finish("assign_ticket", started,
                       {"error_kind": "NOT_FOUND", "message": f"no ticket {ticket_id!r}"},
                       error=f"no ticket {ticket_id!r}", error_kind="NOT_FOUND")

    updates: dict[str, Any] = {}
    for field, table, column in (
        ("team_id", "teams", "team_id"),
        ("assignee_id", "agents", "agent_id"),
    ):
        value = arguments.get(field)
        if not value:
            continue
        exists = connection.execute(
            f"SELECT 1 FROM {table} WHERE {column} = ?", (value,)
        ).fetchone()
        if exists is None:
            return _finish(
                "assign_ticket", started,
                {"error_kind": "NOT_FOUND", "field": field,
                 "message": f"no {table[:-1]} {value!r}"},
                error=f"no {table[:-1]} {value!r}", error_kind="NOT_FOUND",
            )
        updates[field] = value

    assignments = ", ".join(f"{field} = ?" for field in updates)
    connection.execute(
        f"UPDATE tickets SET {assignments} WHERE ticket_id = ?",
        [*updates.values(), ticket_id],
    )
    connection.commit()
    return _finish(
        "assign_ticket", started,
        {"assigned": True, "ticket_id": ticket_id, "fields": sorted(updates)},
        mutation={"table": "tickets", "key": ticket_id, "fields": updates},
    )


def add_comment(environment, arguments: dict[str, Any]) -> ToolResult:
    started = time.perf_counter()
    try:
        _unknown_arguments(arguments, {"ticket_id", "body", "reason_code", "author"})
        ticket_id = _require(arguments, "ticket_id")
        body = _require(arguments, "body")
    except ValidationFailure as failure:
        return _finish("add_comment", started, failure.as_payload(),
                       error=failure.message, error_kind="INVALID_ARGUMENTS")

    connection = environment.connect()
    if connection.execute("SELECT 1 FROM tickets WHERE ticket_id = ?", (ticket_id,)).fetchone() is None:
        return _finish("add_comment", started,
                       {"error_kind": "NOT_FOUND", "message": f"no ticket {ticket_id!r}"},
                       error=f"no ticket {ticket_id!r}", error_kind="NOT_FOUND")

    author = arguments.get("author") or "agent"
    reason_code = arguments.get("reason_code")
    # Sequence-based id, never a clock read, so two identical runs agree.
    next_seq = (connection.execute(
        "SELECT COALESCE(MAX(created_seq), 0) + 1 FROM comments"
    ).fetchone()[0])
    comment_id = f"CMT-{next_seq:05d}"

    connection.execute(
        "INSERT INTO comments (comment_id, ticket_id, author, body, reason_code, created_seq) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (comment_id, ticket_id, author, body, reason_code, next_seq),
    )
    connection.commit()
    return _finish(
        "add_comment", started,
        {"added": True, "comment_id": comment_id, "ticket_id": ticket_id},
        mutation={"table": "comments", "key": comment_id,
                  "fields": {"ticket_id": ticket_id, "reason_code": reason_code}},
    )


def apply_empty_result_policy(result: ToolResult, policy: str) -> ToolResult:
    """Label the execution outcome on a finished tool result.

    Applied centrally rather than at each `_finish` call site: twenty call sites
    are twenty chances for one tool to drift out of the contract, and the whole
    point of an explicit outcome field is that it means the same thing everywhere.

    `baseline` leaves the payload byte-identical to the pre-adoption shape and
    exists only to reproduce a pre-adoption run.
    """
    if policy == "baseline":
        return result

    visible = dict(result.model_visible)
    if result.error is not None:
        visible["outcome"] = EXECUTION_ERROR
    elif (
        result.tool_name in EMPTY_CAPABLE_TOOLS
        and visible.get("row_count") == 0
    ):
        visible["outcome"] = EXECUTION_SUCCESS_EMPTY
        visible["note_empty"] = EMPTY_RESULT_GUIDANCE
    else:
        visible["outcome"] = EXECUTION_SUCCESS_NONEMPTY

    return result.model_copy(update={"model_visible": visible})


def call_tool(
    environment,
    name: str,
    arguments: dict[str, Any],
    identity: ToolCallIdentity | None = None,
    empty_result_policy: str = "accept_empty",
) -> ToolResult:
    """The single entry point the runtime uses.

    Centralizes unknown-tool handling, identity stamping, and the empty-result
    policy, so no caller can accidentally bypass one of them.
    """
    handler = TOOL_DISPATCH.get(name)
    if handler is None:
        result = ToolResult(
            tool_name=name,
            success=False,
            effectful=False,
            model_visible={
                "error_kind": "UNKNOWN_TOOL",
                "message": f"no tool named {name!r}",
                "available_tools": sorted(TOOL_DISPATCH),
            },
            error=f"no tool named {name!r}",
            error_kind="UNKNOWN_TOOL",
        )
    else:
        result = handler(environment, dict(arguments))

    result = apply_empty_result_policy(result, empty_result_policy)
    if identity is not None:
        result = result.model_copy(update={"identity": identity})
    return result


TOOL_DISPATCH = {
    "search_tickets": search_tickets,
    "get_ticket": get_ticket,
    "search_policy": search_policy,
    "list_reference_data": list_reference_data,
    "update_ticket": update_ticket,
    "assign_ticket": assign_ticket,
    "add_comment": add_comment,
}
