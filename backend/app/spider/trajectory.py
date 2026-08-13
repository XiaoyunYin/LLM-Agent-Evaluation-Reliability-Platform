"""Persisted agent trajectories: every step, every episode, checkpoint-resumable.

Three files per run, under `runs/spider_benchmark/<run_id>/`:

- `episodes.jsonl`  one `AgentEpisode` per task
- `steps.jsonl`     one `AgentStep` per model call and per tool call
- `payloads.jsonl`  the large blobs (prompts, model outputs, full SQL results)

**Why payloads are separate.** Steps and episodes are the records metrics are
computed from, so they need to stay small enough to load and scan. A full SQL
result can be tens of thousands of rows. Steps carry a `*_ref` string; the blob
lives in `payloads.jsonl`. The same reason keeps them out of OTel span attributes,
where a large attribute is dropped or truncated by the collector without warning.

**Why resumable.** A 1,034-task run against a paid API takes tens of minutes and
can fail on any single call. `completed_task_ids()` reads what already landed so a
restart continues rather than re-spending. Appending, never rewriting, means a
crash mid-write costs one line, not the file.
"""

from __future__ import annotations

import gzip
import io
import json
import os
import threading
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

from pydantic import BaseModel, ConfigDict, Field


def open_jsonl(path: Path) -> io.TextIOBase:
    """Open a JSONL artifact, transparently accepting a gzipped sibling.

    `payloads.jsonl` is ~20 MB per full run and compresses about 18x. Committing
    it gzipped keeps the full audit trail in the repository at ~1 MB instead of
    dropping it, and every reader goes through here so the compression is
    invisible to the analysis scripts.
    """
    if path.exists():
        return path.open("r", encoding="utf-8")

    compressed = path.with_suffix(path.suffix + ".gz")
    if compressed.exists():
        return gzip.open(compressed, "rt", encoding="utf-8")

    raise FileNotFoundError(f"Neither {path} nor {compressed} exists")


def jsonl_exists(path: Path) -> bool:
    return path.exists() or path.with_suffix(path.suffix + ".gz").exists()

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RUN_ROOT = REPO_ROOT / "runs" / "spider_benchmark"


class StepType(str, Enum):
    MODEL = "model"
    TOOL = "tool"
    VERIFIER = "verifier"


class TerminationReason(str, Enum):
    """P0 taxonomy (plan, Step 12). Deliberately small.

    The split that matters most is `SQL_ERROR` vs `VERIFICATION_FAILED`: the first
    means the agent's final query does not run, the second means it runs and
    returns the wrong thing. Collapsing them would hide which of the two the next
    change should target.

    P2 adds TOKEN_BUDGET, COST_BUDGET, and TIMEOUT.
    """

    SUCCESS = "SUCCESS"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    SQL_ERROR = "SQL_ERROR"
    MAX_STEPS = "MAX_STEPS"
    MODEL_ERROR = "MODEL_ERROR"
    TOOL_ERROR = "TOOL_ERROR"
    NO_FINAL_SQL = "NO_FINAL_SQL"
    # Provider quota or rate limit. Kept distinct from MODEL_ERROR because they
    # demand different responses: MODEL_ERROR is a defect to investigate, whereas
    # RATE_LIMITED means the run must stop and resume in the next quota window.
    # Folding 429s into MODEL_ERROR once produced 90 "model failures" out of 92
    # episodes and hid an exhausted daily quota behind what looked like a bug.
    RATE_LIMITED = "RATE_LIMITED"


# Terminations caused by this platform rather than by the agent's reasoning.
# Reported separately in the metrics so an infrastructure problem can never be
# read as a model quality result.
INFRASTRUCTURE_TERMINATIONS = frozenset(
    {
        TerminationReason.MODEL_ERROR,
        TerminationReason.TOOL_ERROR,
        TerminationReason.RATE_LIMITED,
    }
)

# Terminations that mean the run should stop rather than continue. An episode that
# hit the provider's quota tells us nothing about the agent, and every subsequent
# episode would fail the same way while still costing wall time.
HALTING_TERMINATIONS = frozenset({TerminationReason.RATE_LIMITED})


class AgentStep(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    episode_id: str
    step_index: int
    step_type: StepType

    model_input_ref: str | None = None
    model_output_ref: str | None = None

    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_result_ref: str | None = None
    tool_success: bool | None = None

    input_tokens: int = 0
    # Prompt tokens the API reported as cache hits. Persisted because they are
    # billed at a lower rate: without this field, estimated_cost cannot be
    # re-derived from the record, only inferred by solving backwards from the
    # total. A cost figure that cannot be recomputed from its own artifact is not
    # auditable.
    cached_input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    # Time inside the provider call itself, excluding retry backoff. Latency
    # metrics use this; `latency_ms` includes waiting and so is not a measure of
    # the provider's speed.
    api_latency_ms: float = 0.0
    retry_wait_ms: float = 0.0
    retry_attempts: int = 0
    estimated_cost: float = 0.0

    # What the provider actually served, as opposed to the alias requested.
    # Empty on runs recorded before this field existed.
    model_revision: str | None = None
    system_fingerprint: str | None = None

    span_id: str | None = None
    trace_id: str | None = None
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class AgentEpisode(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    episode_id: str
    run_id: str
    task_id: str

    dataset_version: str
    model_version: str
    prompt_version: str
    tool_schema_version: str

    status: str
    final_sql: str | None = None
    verification_result: dict[str, Any] | None = None
    termination_reason: TerminationReason

    total_steps: int = 0
    model_steps: int = 0
    tool_steps: int = 0
    schema_inspections: int = 0
    sql_executions: int = 0
    sql_execution_errors: int = 0
    # Tool calls whose arguments did not match the declared schema. Counted whether
    # or not validation was enabled, so the ablation measures the same quantity on
    # both sides.
    bad_argument_tool_calls: int = 0
    # P2 damage channel, counted on control and treatment alike.
    empty_successful_executions: int = 0
    submitted_immediately_after_empty: int = 0

    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: float = 0.0
    latency_ms: float = 0.0
    api_latency_ms: float = 0.0
    retry_wait_ms: float = 0.0

    trace_id: str | None = None
    error: str | None = None
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class TrajectoryStore:
    """Append-only JSONL store for one benchmark run."""

    def __init__(self, run_id: str, root: Path | str = DEFAULT_RUN_ROOT) -> None:
        self.run_id = run_id
        self.run_dir = Path(root) / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)

        self.episodes_path = self.run_dir / "episodes.jsonl"
        self.steps_path = self.run_dir / "steps.jsonl"
        self.payloads_path = self.run_dir / "payloads.jsonl"
        self.config_path = self.run_dir / "config.json"

        # Episodes run sequentially today, but the lock costs nothing and means a
        # concurrent runner cannot interleave half-written lines.
        self._lock = threading.Lock()

    def _append(self, path: Path, record: dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self._lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
                # fsync on every episode would dominate runtime; flush is enough to
                # survive a process crash, which is the failure this guards against.
                if path is self.episodes_path:
                    os.fsync(handle.fileno())

    def reset(self) -> None:
        """Clear this run's records so a re-run starts from scratch.

        Necessary because the store is append-only: re-running a task without
        clearing would leave two episodes with the same `task_id` in the file, and
        every metric computed over it would double-count one of them.
        """
        for path in (self.episodes_path, self.steps_path, self.payloads_path):
            if path.exists():
                path.unlink()

    def duplicate_task_ids(self) -> dict[str, int]:
        """Task IDs persisted more than once. Should always be empty."""
        seen: dict[str, int] = {}
        for episode in self.iter_episodes():
            task_id = episode.get("task_id")
            if task_id:
                seen[task_id] = seen.get(task_id, 0) + 1
        return {task_id: count for task_id, count in seen.items() if count > 1}

    def write_config(self, configuration: dict[str, Any]) -> None:
        self.config_path.write_text(
            json.dumps(configuration, indent=2, default=str), encoding="utf-8"
        )

    def store_payload(self, ref: str, kind: str, data: Any) -> str:
        """Persist a large blob and return its reference."""
        self._append(
            self.payloads_path,
            {"ref": ref, "kind": kind, "data": data},
        )
        return ref

    def record_step(self, step: AgentStep) -> None:
        self._append(self.steps_path, step.model_dump(mode="json"))

    def record_episode(self, episode: AgentEpisode) -> None:
        self._append(self.episodes_path, episode.model_dump(mode="json"))

    def completed_task_ids(self) -> set[str]:
        """Task IDs that are genuinely done, for checkpoint resume.

        An episode that terminated for an infrastructure reason is NOT done. It
        measured nothing about the agent, and counting it as complete would make a
        resume skip it forever, silently shrinking the benchmark.

        That is not hypothetical: a real 429 recorded one RATE_LIMITED episode,
        and before this fix `completed_task_ids()` returned that task, so resuming
        would have dropped it from the run permanently while every report still
        claimed the full task set.

        A truncated final line (a crash mid-write) is skipped rather than raising:
        the task simply gets re-run, which is the safe direction.
        """
        if not jsonl_exists(self.episodes_path):
            return set()

        infrastructure = {reason.value for reason in INFRASTRUCTURE_TERMINATIONS}
        done: set[str] = set()
        with open_jsonl(self.episodes_path) as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    if record.get("termination_reason") in infrastructure:
                        continue
                    done.add(record["task_id"])
                except (json.JSONDecodeError, KeyError):
                    continue
        return done

    def incomplete_task_ids(self) -> set[str]:
        """Task IDs recorded only with an infrastructure termination.

        These have a row in `episodes.jsonl` but no usable measurement. A resume
        re-runs them, which means the file can end up with two rows for one task,
        so `prune_infrastructure_episodes()` clears them first.
        """
        if not jsonl_exists(self.episodes_path):
            return set()

        infrastructure = {reason.value for reason in INFRASTRUCTURE_TERMINATIONS}
        incomplete: set[str] = set()
        with open_jsonl(self.episodes_path) as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("termination_reason") in infrastructure:
                    incomplete.add(record.get("task_id", ""))
        return incomplete - {""}

    def prune_infrastructure_episodes(self) -> int:
        """Drop infrastructure-terminated episodes so a resume can replace them.

        Returns how many were removed. Without this, resuming after a quota halt
        would append a second row for the same task and every metric computed over
        the file would double-count it.
        """
        if not jsonl_exists(self.episodes_path):
            return 0

        infrastructure = {reason.value for reason in INFRASTRUCTURE_TERMINATIONS}
        kept: list[str] = []
        removed = 0
        removed_episode_ids: set[str] = set()

        with open_jsonl(self.episodes_path) as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    record = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if record.get("termination_reason") in infrastructure:
                    removed += 1
                    removed_episode_ids.add(record.get("episode_id", ""))
                else:
                    kept.append(stripped)

        if not removed:
            return 0

        with self._lock:
            self.episodes_path.write_text(
                "\n".join(kept) + ("\n" if kept else ""), encoding="utf-8"
            )

        # Their steps go too, or step/episode counts stop reconciling.
        if jsonl_exists(self.steps_path):
            kept_steps: list[str] = []
            with open_jsonl(self.steps_path) as handle:
                for line in handle:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        if json.loads(stripped).get("episode_id") in removed_episode_ids:
                            continue
                    except json.JSONDecodeError:
                        continue
                    kept_steps.append(stripped)
            with self._lock:
                self.steps_path.write_text(
                    "\n".join(kept_steps) + ("\n" if kept_steps else ""),
                    encoding="utf-8",
                )

        return removed

    def iter_episodes(self) -> Iterator[dict[str, Any]]:
        if not jsonl_exists(self.episodes_path):
            return
        with open_jsonl(self.episodes_path) as handle:
            for line in handle:
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue

    def iter_steps(self) -> Iterator[dict[str, Any]]:
        if not jsonl_exists(self.steps_path):
            return
        with open_jsonl(self.steps_path) as handle:
            for line in handle:
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue
