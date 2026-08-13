"""A scripted stand-in for the OpenAI client, for rehearsing the agent loop.

Long, paid runs must be rehearsed before they are launched, and every failure path
(SQL errors, max steps, no final SQL, malformed tool arguments) needs to be
reachable on demand rather than waited for. This client makes both possible at
zero cost.

**Mock results are never a measured result.** A rehearsal run is written under a
run ID prefixed `mockrehearsal_` and `is_mock=True` is recorded in its config, so
no reporting path can mistake one for a real benchmark.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _Function:
    name: str
    arguments: str


@dataclass
class _ToolCall:
    id: str
    function: _Function
    type: str = "function"


@dataclass
class _Message:
    content: str | None
    tool_calls: list[_ToolCall] | None


@dataclass
class _Choice:
    message: _Message
    finish_reason: str


@dataclass
class _PromptTokensDetails:
    cached_tokens: int = 0


@dataclass
class _Usage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    prompt_tokens_details: _PromptTokensDetails = field(
        default_factory=_PromptTokensDetails
    )


@dataclass
class _Response:
    choices: list[_Choice]
    usage: _Usage


def _tool_call(name: str, arguments: dict[str, Any]) -> _ToolCall:
    return _ToolCall(
        id=f"call_{uuid.uuid4().hex[:12]}",
        function=_Function(name=name, arguments=json.dumps(arguments)),
    )


class _Completions:
    def __init__(self, owner: "MockOpenAIClient") -> None:
        self._owner = owner

    def create(self, **kwargs: Any) -> _Response:
        return self._owner._create(**kwargs)


class _Chat:
    def __init__(self, owner: "MockOpenAIClient") -> None:
        self.completions = _Completions(owner)


class MockOpenAIClient:
    """Replays a fixed tool-call script, keyed by turn number.

    `answers` maps a question substring to the SQL the mock will submit, which is
    how a rehearsal exercises both the pass and the fail branch of verification
    without the mock ever seeing gold SQL through the agent's own channel.
    """

    is_mock = True

    def __init__(
        self,
        answers: dict[str, str] | None = None,
        script: list[tuple[str, dict[str, Any]]] | None = None,
        fail_after: int | None = None,
    ) -> None:
        self.chat = _Chat(self)
        self.answers = answers or {}
        self.script = script
        self.fail_after = fail_after
        self.call_count = 0

    def _create(self, **kwargs: Any) -> _Response:
        self.call_count += 1
        messages = kwargs.get("messages", [])

        if self.fail_after is not None and self.call_count > self.fail_after:
            raise RuntimeError("mock model failure")

        # Turn number = how many assistant messages already exist.
        turn = sum(1 for message in messages if message.get("role") == "assistant")

        if self.script is not None:
            if turn < len(self.script):
                name, arguments = self.script[turn]
                calls = [_tool_call(name, arguments)]
            else:
                calls = None
        else:
            calls = self._default_script(turn, messages)

        message = _Message(
            content=None if calls else "I could not determine a query.",
            tool_calls=calls,
        )
        return _Response(
            choices=[_Choice(message=message, finish_reason="tool_calls" if calls else "stop")],
            usage=_Usage(
                prompt_tokens=200 + 60 * turn,
                completion_tokens=40,
                total_tokens=240 + 60 * turn,
            ),
        )

    def _default_script(
        self, turn: int, messages: list[dict[str, Any]]
    ) -> list[_ToolCall] | None:
        if turn == 0:
            return [_tool_call("inspect_schema", {})]

        if turn == 1:
            table = self._first_table(messages)
            return [_tool_call("inspect_schema", {"table_name": table} if table else {})]

        if turn == 2:
            return [_tool_call("execute_sql", {"query": "SELECT 1"})]

        answer = self._lookup_answer(messages)
        if answer is None:
            # No scripted answer: exercise the NO_FINAL_SQL branch.
            return None
        return [_tool_call("submit_answer", {"query": answer})]

    @staticmethod
    def _first_table(messages: list[dict[str, Any]]) -> str | None:
        for message in reversed(messages):
            if message.get("role") != "tool":
                continue
            try:
                payload = json.loads(message.get("content") or "{}")
            except json.JSONDecodeError:
                continue
            tables = payload.get("tables")
            if tables:
                return tables[0]["table"]
        return None

    def _lookup_answer(self, messages: list[dict[str, Any]]) -> str | None:
        question = ""
        for message in messages:
            if message.get("role") == "user":
                question = message.get("content") or ""
                break
        for key, sql in self.answers.items():
            if key and key in question:
                return sql
        return None
