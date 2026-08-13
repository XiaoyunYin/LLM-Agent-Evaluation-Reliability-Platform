"""P4a durability substrate for effectful support-agent tool calls.

This is intentionally Python-native and deterministic. It does not replace the
P3 agent; it gives P4 a small protocol harness where write-ahead intents,
idempotent effects, fencing, lease reclaim and recovery can be tested without
LLM nondeterminism.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from backend.app.support.environment import SupportEnvironment
from backend.app.support.tools import (
    EFFECTFUL_TOOLS,
    TOOL_SCHEMA_VERSION,
    ToolCallIdentity,
    call_tool,
)


class P4State(str, Enum):
    READY = "READY"
    MODEL_DECISION = "MODEL_DECISION"
    INTENT_WRITTEN = "INTENT_WRITTEN"
    STEP_COMPLETED = "STEP_COMPLETED"
    SUCCEEDED = "SUCCEEDED"
    DLQ = "DLQ"


class CrashWindow(str, Enum):
    BEFORE_INTENT_INSERT = "before_intent_insert"
    AFTER_INTENT_BEFORE_EFFECT = "after_intent_before_effect"
    INSIDE_BEFORE_EFFECT_APPLICATION = "inside_before_effect_application"
    AFTER_EFFECT_BEFORE_STEP_COMPLETION = "after_effect_before_step_completion"
    AFTER_STEP_BEFORE_NEXT_MODEL = "after_step_before_next_model"


class P4Crash(RuntimeError):
    """Injected process stop at a named protocol window."""


class ProtocolViolation(RuntimeError):
    """The persisted protocol state is malformed or contradictory."""


class LeaseUnavailable(RuntimeError):
    """An episode is currently owned by another non-expired worker."""


class StaleFenceError(RuntimeError):
    """An old lease owner attempted an effect after a newer token existed."""


@dataclass(frozen=True)
class IntentRecord:
    episode_id: str
    step_index: int
    call_index: int
    tool_name: str
    tool_version: str
    canonical_args: str
    args_hash: str

    @property
    def arguments(self) -> dict[str, Any]:
        return json.loads(self.canonical_args)


@dataclass(frozen=True)
class CrashInjection:
    window: CrashWindow
    step_index: int
    used: bool = False

    def maybe(self, window: CrashWindow, step_index: int) -> "CrashInjection":
        if not self.used and self.window is window and self.step_index == step_index:
            raise P4Crash(f"crash at {window.value} step {step_index}")
        return self

    def consume_if_matches(self, window: CrashWindow, step_index: int) -> tuple[bool, "CrashInjection"]:
        if not self.used and self.window is window and self.step_index == step_index:
            return True, CrashInjection(self.window, self.step_index, used=True)
        return False, self


def canonicalize(arguments: dict[str, Any]) -> str:
    return json.dumps(arguments, sort_keys=True, separators=(",", ":"))


def argument_hash(canonical_arguments: str) -> str:
    return hashlib.sha256(canonical_arguments.encode("utf-8")).hexdigest()


def _json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def _now() -> float:
    return time.time()


class RunnerStore:
    """Runner-owned state: leases, intents, completions and durable budgets."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS p4_sequence (
                name TEXT PRIMARY KEY,
                value INTEGER NOT NULL
            );
            INSERT OR IGNORE INTO p4_sequence (name, value) VALUES ('fence', 0);

            CREATE TABLE IF NOT EXISTS p4_episodes (
                episode_id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                total_steps INTEGER NOT NULL,
                next_step_index INTEGER NOT NULL DEFAULT 0,
                lease_owner TEXT,
                fencing_token INTEGER NOT NULL DEFAULT 0,
                lease_expires_at REAL,
                retry_count INTEGER NOT NULL DEFAULT 0,
                dlq_reason TEXT,
                consumed_model_turns INTEGER NOT NULL DEFAULT 0,
                consumed_tokens INTEGER NOT NULL DEFAULT 0,
                consumed_cost REAL NOT NULL DEFAULT 0.0,
                tool_call_count INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS p4_intents (
                episode_id TEXT NOT NULL,
                step_index INTEGER NOT NULL,
                call_index INTEGER NOT NULL,
                tool_name TEXT NOT NULL,
                tool_version TEXT NOT NULL,
                canonical_args TEXT NOT NULL,
                args_hash TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY (episode_id, step_index, call_index)
            );

            CREATE TABLE IF NOT EXISTS p4_completed_steps (
                episode_id TEXT NOT NULL,
                step_index INTEGER NOT NULL,
                call_index INTEGER NOT NULL,
                result_json TEXT NOT NULL,
                result_ref TEXT NOT NULL,
                completed_at REAL NOT NULL,
                PRIMARY KEY (episode_id, step_index, call_index)
            );
            """
        )
        self.connection.commit()

    def create_episode(self, episode_id: str, total_steps: int) -> None:
        self.connection.execute(
            """
            INSERT OR IGNORE INTO p4_episodes
                (episode_id, state, total_steps, next_step_index)
            VALUES (?, ?, ?, 0)
            """,
            (episode_id, P4State.READY.value, total_steps),
        )
        self.connection.commit()

    def claim_episode(self, episode_id: str, worker_id: str, *, now: float, ttl: float) -> int:
        with self.connection:
            row = self.connection.execute(
                "SELECT * FROM p4_episodes WHERE episode_id = ?", (episode_id,)
            ).fetchone()
            if row is None:
                raise ProtocolViolation(f"unknown episode {episode_id}")
            if row["state"] == P4State.DLQ.value:
                raise ProtocolViolation(f"episode {episode_id} is in DLQ")
            owner = row["lease_owner"]
            expires = row["lease_expires_at"]
            if owner and owner != worker_id and expires is not None and expires > now:
                raise LeaseUnavailable(f"{episode_id} owned by {owner}")

            seq = self.connection.execute(
                "SELECT value FROM p4_sequence WHERE name = 'fence'"
            ).fetchone()["value"] + 1
            self.connection.execute(
                "UPDATE p4_sequence SET value = ? WHERE name = 'fence'", (seq,)
            )
            self.connection.execute(
                """
                UPDATE p4_episodes
                SET lease_owner = ?, fencing_token = ?, lease_expires_at = ?
                WHERE episode_id = ?
                """,
                (worker_id, seq, now + ttl, episode_id),
            )
            return int(seq)

    def heartbeat(self, episode_id: str, worker_id: str, *, now: float, ttl: float) -> None:
        with self.connection:
            row = self.connection.execute(
                "SELECT lease_owner FROM p4_episodes WHERE episode_id = ?", (episode_id,)
            ).fetchone()
            if row is None or row["lease_owner"] != worker_id:
                raise LeaseUnavailable(f"{worker_id} does not own {episode_id}")
            self.connection.execute(
                "UPDATE p4_episodes SET lease_expires_at = ? WHERE episode_id = ?",
                (now + ttl, episode_id),
            )

    def reap_expired(self, *, now: float) -> list[str]:
        rows = self.connection.execute(
            """
            SELECT episode_id FROM p4_episodes
            WHERE lease_owner IS NOT NULL AND lease_expires_at <= ? AND state != ?
            """,
            (now, P4State.DLQ.value),
        ).fetchall()
        expired = [row["episode_id"] for row in rows]
        with self.connection:
            self.connection.execute(
                """
                UPDATE p4_episodes
                SET lease_owner = NULL, lease_expires_at = NULL
                WHERE lease_owner IS NOT NULL AND lease_expires_at <= ? AND state != ?
                """,
                (now, P4State.DLQ.value),
            )
        return expired

    def episode(self, episode_id: str) -> sqlite3.Row:
        row = self.connection.execute(
            "SELECT * FROM p4_episodes WHERE episode_id = ?", (episode_id,)
        ).fetchone()
        if row is None:
            raise ProtocolViolation(f"unknown episode {episode_id}")
        return row

    def current_fence(self, episode_id: str) -> int:
        return int(self.episode(episode_id)["fencing_token"])

    def record_model_decision(self, episode_id: str, *, tokens: int = 1, cost: float = 0.0) -> None:
        with self.connection:
            self.connection.execute(
                """
                UPDATE p4_episodes
                SET state = ?,
                    consumed_model_turns = consumed_model_turns + 1,
                    consumed_tokens = consumed_tokens + ?,
                    consumed_cost = consumed_cost + ?
                WHERE episode_id = ?
                """,
                (P4State.MODEL_DECISION.value, tokens, cost, episode_id),
            )

    def get_intent(self, identity: ToolCallIdentity) -> IntentRecord | None:
        row = self.connection.execute(
            """
            SELECT * FROM p4_intents
            WHERE episode_id = ? AND step_index = ? AND call_index = ?
            """,
            (identity.episode_id, identity.step_index, identity.call_index),
        ).fetchone()
        return _intent_from_row(row) if row else None

    def write_intent(
        self,
        identity: ToolCallIdentity,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        tool_version: str = TOOL_SCHEMA_VERSION,
    ) -> IntentRecord:
        canonical_args = canonicalize(arguments)
        args_hash = argument_hash(canonical_args)
        with self.connection:
            existing = self.get_intent(identity)
            if existing is not None:
                if (
                    existing.tool_name != tool_name
                    or existing.tool_version != tool_version
                    or existing.args_hash != args_hash
                ):
                    raise ProtocolViolation(
                        f"intent conflict for {identity.key()}: persisted winner differs"
                    )
                return existing
            self.connection.execute(
                """
                INSERT INTO p4_intents
                    (episode_id, step_index, call_index, tool_name, tool_version,
                     canonical_args, args_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identity.episode_id,
                    identity.step_index,
                    identity.call_index,
                    tool_name,
                    tool_version,
                    canonical_args,
                    args_hash,
                    _now(),
                ),
            )
            self.connection.execute(
                "UPDATE p4_episodes SET state = ? WHERE episode_id = ?",
                (P4State.INTENT_WRITTEN.value, identity.episode_id),
            )
            return IntentRecord(
                identity.episode_id,
                identity.step_index,
                identity.call_index,
                tool_name,
                tool_version,
                canonical_args,
                args_hash,
            )

    def get_completed(self, identity: ToolCallIdentity) -> dict[str, Any] | None:
        row = self.connection.execute(
            """
            SELECT result_json FROM p4_completed_steps
            WHERE episode_id = ? AND step_index = ? AND call_index = ?
            """,
            (identity.episode_id, identity.step_index, identity.call_index),
        ).fetchone()
        return json.loads(row["result_json"]) if row else None

    def complete_step(
        self,
        identity: ToolCallIdentity,
        result: dict[str, Any],
        *,
        result_ref: str,
        total_steps: int,
    ) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT OR IGNORE INTO p4_completed_steps
                    (episode_id, step_index, call_index, result_json, result_ref, completed_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    identity.episode_id,
                    identity.step_index,
                    identity.call_index,
                    _json(result),
                    result_ref,
                    _now(),
                ),
            )
            next_step = identity.step_index + 1
            state = P4State.SUCCEEDED if next_step >= total_steps else P4State.STEP_COMPLETED
            self.connection.execute(
                """
                UPDATE p4_episodes
                SET state = ?,
                    next_step_index = MAX(next_step_index, ?),
                    tool_call_count = tool_call_count + 1
                WHERE episode_id = ?
                """,
                (state.value, next_step, identity.episode_id),
            )

    def record_failure(self, episode_id: str, reason: str, *, max_retries: int) -> None:
        with self.connection:
            row = self.episode(episode_id)
            retry_count = int(row["retry_count"]) + 1
            state = P4State.DLQ if retry_count >= max_retries else P4State.READY
            self.connection.execute(
                """
                UPDATE p4_episodes
                SET retry_count = ?, state = ?, lease_owner = NULL,
                    lease_expires_at = NULL, dlq_reason = ?
                WHERE episode_id = ?
                """,
                (
                    retry_count,
                    state.value,
                    reason if state is P4State.DLQ else None,
                    episode_id,
                ),
            )

    def intent_count(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM p4_intents").fetchone()[0])

    def completed_count(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM p4_completed_steps").fetchone()[0])

    def close(self) -> None:
        self.connection.close()


def _intent_from_row(row: sqlite3.Row) -> IntentRecord:
    return IntentRecord(
        episode_id=row["episode_id"],
        step_index=int(row["step_index"]),
        call_index=int(row["call_index"]),
        tool_name=row["tool_name"],
        tool_version=row["tool_version"],
        canonical_args=row["canonical_args"],
        args_hash=row["args_hash"],
    )


class EffectStore:
    """Effect-owned state: business mutation, idempotency result and fencing."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS p4_effect_fence (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                current_token INTEGER NOT NULL
            );
            INSERT OR IGNORE INTO p4_effect_fence (singleton, current_token)
            VALUES (1, 0);

            CREATE TABLE IF NOT EXISTS p4_effect_results (
                episode_id TEXT NOT NULL,
                step_index INTEGER NOT NULL,
                call_index INTEGER NOT NULL,
                tool_name TEXT NOT NULL,
                tool_version TEXT NOT NULL,
                canonical_args TEXT NOT NULL,
                args_hash TEXT NOT NULL,
                fencing_token INTEGER NOT NULL,
                result_json TEXT NOT NULL,
                mutation_json TEXT NOT NULL,
                completed_at REAL NOT NULL,
                PRIMARY KEY (episode_id, step_index, call_index)
            );

            CREATE TABLE IF NOT EXISTS p4_effect_attempts (
                attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                episode_id TEXT NOT NULL,
                step_index INTEGER NOT NULL,
                call_index INTEGER NOT NULL,
                tool_name TEXT NOT NULL,
                fencing_token INTEGER NOT NULL,
                current_token INTEGER NOT NULL,
                accepted INTEGER NOT NULL,
                rejected_reason TEXT,
                created_at REAL NOT NULL
            );
            """
        )
        self.connection.commit()

    def install_fence(self, token: int) -> None:
        with self.connection:
            self.connection.execute(
                """
                UPDATE p4_effect_fence
                SET current_token = MAX(current_token, ?)
                WHERE singleton = 1
                """,
                (token,),
            )

    def current_token(self) -> int:
        return int(
            self.connection.execute(
                "SELECT current_token FROM p4_effect_fence WHERE singleton = 1"
            ).fetchone()["current_token"]
        )

    def get_result(self, identity: ToolCallIdentity) -> dict[str, Any] | None:
        row = self.connection.execute(
            """
            SELECT result_json FROM p4_effect_results
            WHERE episode_id = ? AND step_index = ? AND call_index = ?
            """,
            (identity.episode_id, identity.step_index, identity.call_index),
        ).fetchone()
        return json.loads(row["result_json"]) if row else None

    def invoke_effect(
        self,
        intent: IntentRecord,
        fencing_token: int,
        *,
        crash_before_application: bool = False,
    ) -> dict[str, Any]:
        if intent.tool_name not in EFFECTFUL_TOOLS:
            raise ProtocolViolation(f"{intent.tool_name} is not effectful")

        identity = ToolCallIdentity(
            episode_id=intent.episode_id,
            step_index=intent.step_index,
            call_index=intent.call_index,
        )
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            current = self.current_token()
            if fencing_token != current:
                self._record_attempt(identity, intent.tool_name, fencing_token, current, False, "STALE_FENCE")
                self.connection.commit()
                raise StaleFenceError(
                    f"stale fence {fencing_token}; current fence is {current}"
                )

            existing = self.connection.execute(
                """
                SELECT * FROM p4_effect_results
                WHERE episode_id = ? AND step_index = ? AND call_index = ?
                """,
                (intent.episode_id, intent.step_index, intent.call_index),
            ).fetchone()
            if existing is not None:
                if (
                    existing["tool_name"] != intent.tool_name
                    or existing["tool_version"] != intent.tool_version
                    or existing["args_hash"] != intent.args_hash
                ):
                    raise ProtocolViolation(
                        f"idempotency conflict for {identity.key()}: arguments differ"
                    )
                self._record_attempt(identity, intent.tool_name, fencing_token, current, True, None)
                self.connection.commit()
                return json.loads(existing["result_json"])

            if crash_before_application:
                self.connection.rollback()
                raise P4Crash(
                    f"crash at {CrashWindow.INSIDE_BEFORE_EFFECT_APPLICATION.value} "
                    f"step {intent.step_index}"
                )

            result, mutation = self._apply_business_mutation(intent.tool_name, intent.arguments)
            self.connection.execute(
                """
                INSERT INTO p4_effect_results
                    (episode_id, step_index, call_index, tool_name, tool_version,
                     canonical_args, args_hash, fencing_token, result_json,
                     mutation_json, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    intent.episode_id,
                    intent.step_index,
                    intent.call_index,
                    intent.tool_name,
                    intent.tool_version,
                    intent.canonical_args,
                    intent.args_hash,
                    fencing_token,
                    _json(result),
                    _json(mutation),
                    _now(),
                ),
            )
            self._record_attempt(identity, intent.tool_name, fencing_token, current, True, None)
            self.connection.commit()
            return result
        except (P4Crash, StaleFenceError):
            raise
        except Exception:
            self.connection.rollback()
            raise

    def _record_attempt(
        self,
        identity: ToolCallIdentity,
        tool_name: str,
        fencing_token: int,
        current_token: int,
        accepted: bool,
        rejected_reason: str | None,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO p4_effect_attempts
                (episode_id, step_index, call_index, tool_name, fencing_token,
                 current_token, accepted, rejected_reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                identity.episode_id,
                identity.step_index,
                identity.call_index,
                tool_name,
                fencing_token,
                current_token,
                1 if accepted else 0,
                rejected_reason,
                _now(),
            ),
        )

    def _apply_business_mutation(self, tool_name: str, arguments: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        if tool_name == "update_ticket":
            return self._update_ticket(arguments)
        if tool_name == "assign_ticket":
            return self._assign_ticket(arguments)
        if tool_name == "add_comment":
            return self._add_comment(arguments)
        raise ProtocolViolation(f"unsupported effectful tool {tool_name}")

    def _update_ticket(self, arguments: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        ticket_id = _required(arguments, "ticket_id")
        updates = {
            field: (1 if value is True else 0 if value is False else value)
            for field, value in arguments.items()
            if field in {"priority", "status", "escalated"} and value is not None
        }
        if not updates:
            raise ProtocolViolation("update_ticket requires a mutable field")
        if self.connection.execute(
            "SELECT 1 FROM tickets WHERE ticket_id = ?", (ticket_id,)
        ).fetchone() is None:
            raise ProtocolViolation(f"no ticket {ticket_id!r}")
        assignments = ", ".join(f"{field} = ?" for field in updates)
        self.connection.execute(
            f"UPDATE tickets SET {assignments} WHERE ticket_id = ?",
            [*updates.values(), ticket_id],
        )
        result = {"updated": True, "ticket_id": ticket_id, "fields": sorted(updates)}
        mutation = {"table": "tickets", "key": ticket_id, "fields": updates}
        return result, mutation

    def _assign_ticket(self, arguments: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        ticket_id = _required(arguments, "ticket_id")
        if self.connection.execute(
            "SELECT 1 FROM tickets WHERE ticket_id = ?", (ticket_id,)
        ).fetchone() is None:
            raise ProtocolViolation(f"no ticket {ticket_id!r}")
        updates = {
            field: arguments[field]
            for field in ("team_id", "assignee_id")
            if arguments.get(field)
        }
        if not updates:
            raise ProtocolViolation("assign_ticket requires team_id or assignee_id")
        for field, table, column in (
            ("team_id", "teams", "team_id"),
            ("assignee_id", "agents", "agent_id"),
        ):
            value = updates.get(field)
            if value and self.connection.execute(
                f"SELECT 1 FROM {table} WHERE {column} = ?", (value,)
            ).fetchone() is None:
                raise ProtocolViolation(f"no {table[:-1]} {value!r}")
        assignments = ", ".join(f"{field} = ?" for field in updates)
        self.connection.execute(
            f"UPDATE tickets SET {assignments} WHERE ticket_id = ?",
            [*updates.values(), ticket_id],
        )
        result = {"assigned": True, "ticket_id": ticket_id, "fields": sorted(updates)}
        mutation = {"table": "tickets", "key": ticket_id, "fields": updates}
        return result, mutation

    def _add_comment(self, arguments: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        ticket_id = _required(arguments, "ticket_id")
        body = _required(arguments, "body")
        if self.connection.execute(
            "SELECT 1 FROM tickets WHERE ticket_id = ?", (ticket_id,)
        ).fetchone() is None:
            raise ProtocolViolation(f"no ticket {ticket_id!r}")
        author = arguments.get("author") or "agent"
        reason_code = arguments.get("reason_code")
        next_seq = self.connection.execute(
            "SELECT COALESCE(MAX(created_seq), 0) + 1 FROM comments"
        ).fetchone()[0]
        comment_id = f"CMT-{next_seq:05d}"
        self.connection.execute(
            """
            INSERT INTO comments (comment_id, ticket_id, author, body, reason_code, created_seq)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (comment_id, ticket_id, author, body, reason_code, next_seq),
        )
        result = {"added": True, "comment_id": comment_id, "ticket_id": ticket_id}
        mutation = {
            "table": "comments",
            "key": comment_id,
            "fields": {"ticket_id": ticket_id, "reason_code": reason_code},
        }
        return result, mutation

    def effect_count(self) -> int:
        return int(self.connection.execute("SELECT COUNT(*) FROM p4_effect_results").fetchone()[0])

    def stale_attempts(self) -> int:
        return int(
            self.connection.execute(
                "SELECT COUNT(*) FROM p4_effect_attempts WHERE rejected_reason = 'STALE_FENCE'"
            ).fetchone()[0]
        )

    def stale_accepted(self) -> int:
        return int(
            self.connection.execute(
                """
                SELECT COUNT(*) FROM p4_effect_attempts
                WHERE accepted = 1 AND fencing_token != current_token
                """
            ).fetchone()[0]
        )

    def duplicate_business_mutations(self) -> int:
        rows = self.connection.execute(
            "SELECT mutation_json, COUNT(*) AS n FROM p4_effect_results GROUP BY mutation_json HAVING n > 1"
        ).fetchall()
        return sum(int(row["n"]) - 1 for row in rows)


def _required(arguments: dict[str, Any], field: str) -> Any:
    value = arguments.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ProtocolViolation(f"{field} is required")
    return value


class DeterministicP4Runner:
    """Executes a scripted trajectory through the P4a protocol."""

    def __init__(
        self,
        runner_store: RunnerStore,
        effect_store: EffectStore,
        environment: SupportEnvironment,
        *,
        lease_ttl: float = 10.0,
    ) -> None:
        self.runner_store = runner_store
        self.effect_store = effect_store
        self.environment = environment
        self.lease_ttl = lease_ttl

    def run(
        self,
        episode_id: str,
        trajectory: list[tuple[str, dict[str, Any]]],
        *,
        worker_id: str,
        now: float,
        crash: CrashInjection | None = None,
    ) -> CrashInjection | None:
        self.runner_store.create_episode(episode_id, len(trajectory))
        token = self.runner_store.claim_episode(
            episode_id, worker_id, now=now, ttl=self.lease_ttl
        )
        self.effect_store.install_fence(token)
        crash_state = crash

        while True:
            episode = self.runner_store.episode(episode_id)
            next_step = int(episode["next_step_index"])
            if next_step >= len(trajectory):
                return crash_state

            name, arguments = trajectory[next_step]
            identity = ToolCallIdentity(
                episode_id=episode_id, step_index=next_step, call_index=0
            )
            if self.runner_store.get_completed(identity) is not None:
                continue

            intent = self.runner_store.get_intent(identity)
            if intent is None:
                self.runner_store.record_model_decision(episode_id)
                if crash_state:
                    matched, crash_state = crash_state.consume_if_matches(
                        CrashWindow.BEFORE_INTENT_INSERT, next_step
                    )
                    if matched:
                        raise P4Crash(
                            f"crash at {CrashWindow.BEFORE_INTENT_INSERT.value} step {next_step}"
                        )
                intent = self.runner_store.write_intent(identity, name, dict(arguments))

            if crash_state:
                matched, crash_state = crash_state.consume_if_matches(
                    CrashWindow.AFTER_INTENT_BEFORE_EFFECT, next_step
                )
                if matched:
                    raise P4Crash(
                        f"crash at {CrashWindow.AFTER_INTENT_BEFORE_EFFECT.value} step {next_step}"
                    )

            result: dict[str, Any]
            if name in EFFECTFUL_TOOLS:
                existing = self.effect_store.get_result(identity)
                if existing is None:
                    crash_before_application = False
                    if crash_state:
                        crash_before_application, crash_state = crash_state.consume_if_matches(
                            CrashWindow.INSIDE_BEFORE_EFFECT_APPLICATION, next_step
                        )
                    result = self.effect_store.invoke_effect(
                        intent,
                        token,
                        crash_before_application=crash_before_application,
                    )
                else:
                    result = existing
                if crash_state:
                    matched, crash_state = crash_state.consume_if_matches(
                        CrashWindow.AFTER_EFFECT_BEFORE_STEP_COMPLETION, next_step
                    )
                    if matched:
                        raise P4Crash(
                            f"crash at {CrashWindow.AFTER_EFFECT_BEFORE_STEP_COMPLETION.value} "
                            f"step {next_step}"
                        )
            else:
                tool_result = call_tool(
                    self.environment,
                    name,
                    intent.arguments,
                    identity=identity,
                    empty_result_policy="accept_empty",
                )
                result = tool_result.model_visible
                if not tool_result.success:
                    raise ProtocolViolation(tool_result.error or f"{name} failed")

            self.runner_store.complete_step(
                identity,
                result,
                result_ref=identity.key(),
                total_steps=len(trajectory),
            )
            if crash_state:
                matched, crash_state = crash_state.consume_if_matches(
                    CrashWindow.AFTER_STEP_BEFORE_NEXT_MODEL, next_step
                )
                if matched:
                    raise P4Crash(
                        f"crash at {CrashWindow.AFTER_STEP_BEFORE_NEXT_MODEL.value} "
                        f"step {next_step}"
                    )


def verify_invariants(runner_store: RunnerStore, effect_store: EffectStore) -> dict[str, int]:
    """Return protocol invariant violation counts."""
    runner = runner_store.connection
    effect = effect_store.connection
    intent_keys = {
        (row["episode_id"], row["step_index"], row["call_index"])
        for row in runner.execute("SELECT episode_id, step_index, call_index FROM p4_intents")
    }
    completed_keys = {
        (row["episode_id"], row["step_index"], row["call_index"])
        for row in runner.execute("SELECT episode_id, step_index, call_index FROM p4_completed_steps")
    }
    effect_keys = {
        (row["episode_id"], row["step_index"], row["call_index"])
        for row in effect.execute("SELECT episode_id, step_index, call_index FROM p4_effect_results")
    }
    return {
        "durable_intent_duplicates": _duplicate_count(
            runner,
            "p4_intents",
            ("episode_id", "step_index", "call_index"),
        ),
        "effect_result_duplicates": _duplicate_count(
            effect,
            "p4_effect_results",
            ("episode_id", "step_index", "call_index"),
        ),
        "effects_without_intent": len(effect_keys - intent_keys),
        "completed_without_result": len(completed_keys - (effect_keys | intent_keys)),
        "stale_fenced_effects_accepted": effect_store.stale_accepted(),
        "duplicate_business_mutations": effect_store.duplicate_business_mutations(),
    }


def _duplicate_count(connection: sqlite3.Connection, table: str, columns: Iterable[str]) -> int:
    joined = ", ".join(columns)
    rows = connection.execute(
        f"SELECT COUNT(*) AS n FROM (SELECT {joined}, COUNT(*) AS c FROM {table} "
        f"GROUP BY {joined} HAVING c > 1)"
    ).fetchone()
    return int(rows["n"])
