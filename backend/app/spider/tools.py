"""The agent's only access to a database: `inspect_schema` and `execute_sql`.

**Why schema is a tool and not part of the prompt.** Most published Spider systems
serialize the entire schema into the prompt. This one does not (P0 plan, Step 5).
That makes the absolute accuracy number lower and not leaderboard-comparable - a
tradeoff documented in `docs/benchmark-protocol.md` - but it makes the thing under
test an *agent*: it has to decide what it needs to know and go get it. Tool-choice
behaviour is what this platform measures, and a fixed retrieve-then-generate
sequence measures none of it.

**Why results are capped.** `execute_sql` returns at most `MAX_VISIBLE_ROWS` to the
model while the full result is kept in the trajectory record. A query returning
50,000 rows would otherwise blow the context window, cost more than the task is
worth, and make token accounting a function of the data rather than the agent.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field

from backend.app.spider.environment import EpisodeDatabase, ReadOnlyViolation

# Explicit execution outcomes (P2, Intervention A).
#
# The baseline response said `error: null` and `rows: []` for a valid query that
# matched nothing, which is accurate but reads as failure: measured across five
# baseline runs, agents that had already executed a passing query abandoned it in
# 24-32 episodes per run, and in 26 of the 39 affected tasks the passing query
# returned zero rows.
#
# Naming the outcome removes the ambiguity without changing what is true. An empty
# result is still an empty result; it is simply labelled as a successful execution
# rather than left to be inferred from an absent error.
EXECUTION_SUCCESS_NONEMPTY = "EXECUTION_SUCCESS_NONEMPTY"
EXECUTION_SUCCESS_EMPTY = "EXECUTION_SUCCESS_EMPTY"
EXECUTION_ERROR = "EXECUTION_ERROR"

# Guidance attached to an empty successful execution under the treatment policy.
# Deliberately not an instruction to submit: it corrects a false inference without
# replacing it with the opposite false inference.
EMPTY_RESULT_GUIDANCE = (
    "The query executed successfully and matched no rows. An empty result is a "
    "valid answer when the question genuinely has no matching rows - it is not by "
    "itself evidence that the SQL is wrong. Re-check the query against the schema "
    "and the question; if it is correct, submit it."
)

# Bumped whenever a tool's name, arguments, or response shape changes. Persisted
# on every episode so a measured accuracy delta can be attributed to a tool-schema
# change rather than silently absorbed.
#
# v2: argument validation. v1 read `arguments.get("table_name")` and ignored
# everything else, so a call of `inspect_schema({"table": "course"})` - which the
# model does make - silently returned the *table list* instead of the requested
# table, looking like a successful response. Measured in the Step 13 smoke run:
# 3 of 10 episodes burned their entire step budget re-requesting a description
# they could never receive. A tool that accepts a wrong argument and answers
# plausibly is invisible to its caller; unknown arguments are now rejected with a
# message naming the accepted parameters.
TOOL_SCHEMA_VERSION = "spider_tools_v2"

# Rows the model sees. The full result still reaches the trajectory record.
MAX_VISIBLE_ROWS = 20
# Per-cell character cap. One BLOB or long text column should not consume the
# context budget that twenty rows were meant to fit in.
MAX_CELL_CHARS = 200
# Wall-clock cap for a single agent query. Spider dev has databases where a
# careless cross join runs for minutes.
QUERY_TIMEOUT_SECONDS = 30.0


class ToolResult(BaseModel):
    """What a tool returns.

    Split deliberately in two:

    - `model_visible` is the truncated payload serialized into the conversation.
    - `full_result` is everything, persisted to the trajectory and never sent to
      the model.

    Keeping both on one object is what lets a run be audited later without having
    paid to put the whole result in context.
    """

    tool_name: str
    success: bool
    model_visible: dict[str, Any]
    full_result: dict[str, Any] = Field(default_factory=dict)
    latency_ms: float = 0.0
    error: str | None = None


def _truncate_cell(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_CELL_CHARS:
        return value[:MAX_CELL_CHARS] + f"... [{len(value)} chars]"
    if isinstance(value, (bytes, bytearray)):
        return f"<binary {len(value)} bytes>"
    return value


def _serialize_rows(rows: list[tuple]) -> list[list[Any]]:
    return [[_truncate_cell(cell) for cell in row] for row in rows]


def inspect_schema(
    database: EpisodeDatabase,
    table_name: str | None = None,
) -> ToolResult:
    """Discover schema.

    With no `table_name`, returns the table list plus each table's column count -
    enough for the model to choose where to look, without serializing every column
    of every table. With a `table_name`, returns that table's columns, types,
    primary key, and foreign keys.
    """
    started = time.perf_counter()

    def finish(
        visible: dict[str, Any],
        full: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> ToolResult:
        return ToolResult(
            tool_name="inspect_schema",
            success=error is None,
            model_visible=visible,
            full_result=full if full is not None else visible,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            error=error,
        )

    try:
        connection = database.connect()

        table_rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        table_names = [row[0] for row in table_rows]

        if table_name is None:
            tables = []
            for name in table_names:
                columns = connection.execute(
                    f'PRAGMA table_info("{name}")'
                ).fetchall()
                tables.append({"table": name, "column_count": len(columns)})
            return finish({"tables": tables})

        if table_name not in table_names:
            # A wrong table name is an ordinary agent mistake, so it comes back as
            # a readable error the model can recover from rather than an exception
            # that ends the episode.
            return finish(
                {
                    "error": f"No table named {table_name!r}.",
                    "available_tables": table_names,
                },
                error=f"unknown table {table_name!r}",
            )

        columns = connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
        foreign_keys = connection.execute(
            f'PRAGMA foreign_key_list("{table_name}")'
        ).fetchall()

        visible = {
            "table": table_name,
            "columns": [
                {
                    "name": column[1],
                    "type": column[2] or "UNKNOWN",
                    "not_null": bool(column[3]),
                    "primary_key": bool(column[5]),
                }
                for column in columns
            ],
            "primary_key": [column[1] for column in columns if column[5]],
            "foreign_keys": [
                {
                    "column": fk[3],
                    "references_table": fk[2],
                    "references_column": fk[4],
                }
                for fk in foreign_keys
            ],
        }
        return finish(visible)

    except Exception as error:  # noqa: BLE001 - reported as a tool failure
        return finish(
            {"error": f"schema inspection failed: {error}"},
            error=f"{type(error).__name__}: {error}",
        )


def execute_sql(
    database: EpisodeDatabase,
    query: str,
    empty_result_policy: str = "baseline",
) -> ToolResult:
    """Run a read-only query and return a capped, structured result.

    Errors are returned, not raised. An agent that writes `no such column: foo`
    should get that string back and be able to fix it; raising would turn an
    ordinary recoverable mistake into an episode-ending infrastructure failure and
    corrupt the failure-category breakdown.
    """
    started = time.perf_counter()

    def finish(
        visible: dict[str, Any],
        full: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> ToolResult:
        return ToolResult(
            tool_name="execute_sql",
            success=error is None,
            model_visible=visible,
            full_result=full if full is not None else visible,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            error=error,
        )

    def failure(message: str) -> ToolResult:
        visible = {"columns": [], "rows": [], "row_count": 0, "error": message}
        if empty_result_policy != "baseline":
            visible["outcome"] = EXECUTION_ERROR
        return finish(visible, error=message)

    if not isinstance(query, str) or not query.strip():
        return failure("execute_sql requires a non-empty 'query' argument.")

    try:
        columns, rows = database.execute(query, timeout_seconds=QUERY_TIMEOUT_SECONDS)
    except ReadOnlyViolation as error:
        return failure(str(error))
    except Exception as error:  # noqa: BLE001 - SQL errors are expected agent output
        return failure(f"{type(error).__name__}: {error}")

    visible_rows = _serialize_rows(rows[:MAX_VISIBLE_ROWS])
    visible: dict[str, Any] = {
        "columns": columns,
        "rows": visible_rows,
        "row_count": len(rows),
        "error": None,
    }

    if empty_result_policy != "baseline":
        # The only behavioural change in Intervention A. Under `baseline` the
        # response is byte-identical to every prior run, so a control run on this
        # commit is a true control.
        if rows:
            visible["outcome"] = EXECUTION_SUCCESS_NONEMPTY
        else:
            visible["outcome"] = EXECUTION_SUCCESS_EMPTY
            visible["note_empty"] = EMPTY_RESULT_GUIDANCE
    if len(rows) > MAX_VISIBLE_ROWS:
        visible["truncated"] = True
        visible["note"] = (
            f"Showing the first {MAX_VISIBLE_ROWS} of {len(rows)} rows. "
            "The full result is recorded but not shown."
        )

    return finish(
        visible,
        full={
            "columns": columns,
            "rows": _serialize_rows(rows),
            "row_count": len(rows),
            "error": None,
        },
    )


# OpenAI tool-calling schemas. Descriptions are part of the measured system: they
# are what the model reads to decide between the two tools, so a wording change is
# a `TOOL_SCHEMA_VERSION` bump, not a comment edit.
TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "inspect_schema",
            "description": (
                "Inspect the database schema. Call with no arguments to list the "
                "tables. Call with a table name to get that table's columns, "
                "types, primary key, and foreign keys."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": (
                            "Table to describe. Omit to list all tables first."
                        ),
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_sql",
            "description": (
                "Execute a single read-only SELECT query against the database and "
                "return the result. Use this to check that a query runs and returns "
                "what you expect before submitting it as the final answer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "One SQLite SELECT statement.",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_answer",
            "description": (
                "Submit the final SQL query that answers the question. Call this "
                "exactly once, when you are confident the query is correct. This "
                "ends the episode."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The final SQLite SELECT statement.",
                    }
                },
                "required": ["query"],
            },
        },
    },
]

TOOL_NAMES = tuple(spec["function"]["name"] for spec in TOOL_SPECS)

_TOOL_PARAMETERS: dict[str, dict[str, Any]] = {
    spec["function"]["name"]: spec["function"]["parameters"] for spec in TOOL_SPECS
}


def validate_tool_arguments(tool_name: str, arguments: dict[str, Any]) -> str | None:
    """Check arguments against the declared schema. Returns an error, or None.

    Derived from `TOOL_SPECS` rather than hand-written per tool, so the validation
    cannot drift from the schema the model was shown.

    The error text names the accepted parameters, because a rejection the model
    cannot act on is only marginally better than a silent wrong answer.
    """
    parameters = _TOOL_PARAMETERS.get(tool_name)
    if parameters is None:
        return f"Unknown tool {tool_name!r}."

    accepted = set(parameters.get("properties", {}))
    unknown = sorted(set(arguments) - accepted)
    if unknown:
        return (
            f"Unknown argument(s) {unknown} for {tool_name}. "
            f"Accepted argument(s): {sorted(accepted)}."
        )

    missing = sorted(set(parameters.get("required", [])) - set(arguments))
    if missing:
        return f"Missing required argument(s) {missing} for {tool_name}."

    return None
