"""Adapt Spider tasks into the platform's internal evaluation abstractions.

This is the seam the P0 plan asks for: everything downstream of here works in
`SQLTask` / `EvalCase` and never reads Spider's raw JSON, so swapping in BIRD or
a private SQL benchmark later means writing one loader, not editing the runner.

It also owns exclusion-list application. Exclusions live in `docs/LOCKED_INPUTS.md`,
frozen by `scripts/qa_spider_evaluator.py` before any agent ran, and are applied
here rather than at each call site so no code path can quietly skip a task.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from backend.app.eval_case import EvalCase, TaskType
from backend.app.spider.loader import (
    DEFAULT_DATASET_ROOT,
    SQLTask,
    load_pin,
    load_spider_tasks,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
LOCKED_INPUTS_PATH = REPO_ROOT / "docs" / "LOCKED_INPUTS.md"

# Bumped whenever the normalization below changes shape, so a run artifact records
# which adapter produced its tasks.
ADAPTER_VERSION = "spider_adapter_v1"

_EXCLUSION_ROW = re.compile(r"^\|\s*`(?P<task_id>[^`]+)`\s*\|")


class ExclusionListError(Exception):
    """Raised when the frozen exclusion list cannot be read."""


def load_exclusions(path: Path | str = LOCKED_INPUTS_PATH) -> dict[str, str]:
    """Parse frozen task exclusions out of `LOCKED_INPUTS.md`.

    Returns `{task_id: reason}`. An absent file is an error rather than an empty
    dict: "no exclusions recorded" and "verifier QA never ran" must not look the
    same to a benchmark run.
    """
    exclusion_path = Path(path)
    if not exclusion_path.exists():
        raise ExclusionListError(
            f"No frozen exclusion list at {exclusion_path}. "
            "Run: python scripts/qa_spider_evaluator.py --split dev"
        )

    text = exclusion_path.read_text(encoding="utf-8")
    section = text.split("## Frozen exclusion list", 1)
    if len(section) < 2:
        raise ExclusionListError(
            f"{exclusion_path} has no '## Frozen exclusion list' section."
        )

    body = section[1].split("## Rules", 1)[0]
    exclusions: dict[str, str] = {}
    for line in body.splitlines():
        match = _EXCLUSION_ROW.match(line.strip())
        if not match:
            continue
        columns = [cell.strip() for cell in line.strip().strip("|").split("|")]
        task_id = match.group("task_id")
        reason = columns[-1] if len(columns) >= 4 else "unspecified"
        exclusions[task_id] = reason

    return exclusions


class SpiderTaskSet:
    """The valid task set for one benchmark run, with exclusions applied."""

    def __init__(
        self,
        split: str,
        tasks: list[SQLTask],
        excluded: dict[str, str],
        pin: dict[str, Any],
    ) -> None:
        self.split = split
        self.tasks = tasks
        self.excluded = excluded
        self.pin = pin

    @property
    def dataset_version(self) -> str:
        """A version string that changes whenever the underlying data changes."""
        return f"{self.pin['benchmark']}:{self.split}:{self.pin['dev_json_sha256'][:12]}"

    def configuration(self) -> dict[str, Any]:
        """The reproducibility block persisted with every run (plan Step 15)."""
        return {
            "dataset": "spider",
            "dataset_version": self.dataset_version,
            "split": self.split,
            "adapter_version": ADAPTER_VERSION,
            "archive_sha256": self.pin["archive_sha256"],
            "dev_json_sha256": self.pin["dev_json_sha256"],
            "tables_json_sha256": self.pin["tables_json_sha256"],
            "evaluator_file_sha256": self.pin.get("evaluator_file_sha256", {}),
            "valid_task_count": len(self.tasks),
            "valid_task_ids": [task.task_id for task in self.tasks],
            "excluded_task_ids": sorted(self.excluded),
            "excluded_reasons": self.excluded,
        }

    def __len__(self) -> int:
        return len(self.tasks)

    def __iter__(self):
        return iter(self.tasks)


def build_task_set(
    split: str = "dev",
    dataset_root: Path | str = DEFAULT_DATASET_ROOT,
    exclusions_path: Path | str = LOCKED_INPUTS_PATH,
) -> SpiderTaskSet:
    all_tasks = load_spider_tasks(split, dataset_root)
    excluded = load_exclusions(exclusions_path)
    valid = [task for task in all_tasks if task.task_id not in excluded]

    return SpiderTaskSet(
        split=split,
        tasks=valid,
        excluded={
            task_id: reason
            for task_id, reason in excluded.items()
            if any(task.task_id == task_id for task in all_tasks)
        },
        pin=load_pin(dataset_root),
    )


def to_eval_case(task: SQLTask) -> EvalCase:
    """Normalize a `SQLTask` into the platform's `EvalCase`.

    `expected_answer` carries the gold SQL. That is deliberately *not* what the
    agent is scored against by string comparison - execution verification is the
    only correctness signal - but keeping it on the case means the existing runner,
    dataset loader, and storage paths work unchanged.
    """
    return EvalCase(
        id=task.task_id,
        question=task.question,
        expected_answer=task.gold_query,
        task_type=TaskType.AGENTIC_TOOL_CALLING,
        metadata={
            "dataset": "spider",
            "split": task.split,
            "database_id": task.database_id,
            "database_path": task.database_path,
            "adapter_version": ADAPTER_VERSION,
            **task.metadata,
        },
    )


def to_eval_cases(tasks: list[SQLTask]) -> list[EvalCase]:
    return [to_eval_case(task) for task in tasks]
