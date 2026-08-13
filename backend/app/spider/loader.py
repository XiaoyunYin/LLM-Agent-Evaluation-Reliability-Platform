"""Load pinned Spider examples into the project's internal SQL task format.

The runner never sees Spider's raw JSON. It sees `SQLTask`, which carries exactly
what an episode needs: the question, which database to open, where that database
lives on disk, and the gold query the verifier compares against.

Split discipline (P0 plan, Step 1): dev and train are loaded through the same
function but are never mixed in a reported benchmark. The split is recorded on
every task so a run artifact can be checked after the fact.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATASET_ROOT = REPO_ROOT / "datasets" / "spider"

SPLIT_FILES = {
    "dev": "dev.json",
    "train": "train_spider.json",
    "train_others": "train_others.json",
}


class SpiderDatasetError(Exception):
    """Raised when the pinned dataset is missing, incomplete, or inconsistent."""


class SQLTask(BaseModel):
    """One Spider example, normalized.

    `task_id` is deterministic (`spider_dev_0042`), not a random UUID, so the same
    example carries the same identifier across every run. Metrics that join runs
    on task ID depend on that.
    """

    task_id: str
    question: str
    database_id: str
    database_path: str
    gold_query: str
    split: str
    metadata: dict[str, Any] = Field(default_factory=dict)


def load_pin(dataset_root: Path | str = DEFAULT_DATASET_ROOT) -> dict[str, Any]:
    """Return the benchmark pin written by `scripts/download_spider.py`."""
    pin_path = Path(dataset_root) / "PIN.json"
    if not pin_path.exists():
        raise SpiderDatasetError(
            f"No benchmark pin at {pin_path}. Run: python scripts/download_spider.py"
        )
    return json.loads(pin_path.read_text(encoding="utf-8"))


def database_path_for(database_id: str, dataset_root: Path | str = DEFAULT_DATASET_ROOT) -> Path:
    """Resolve the source SQLite file for a Spider `db_id`.

    Resolved once at load time rather than at episode time so a missing database
    fails the whole load instead of surfacing as a mid-benchmark task failure that
    looks like an agent error.
    """
    root = Path(dataset_root)
    candidate = root / "database" / database_id / f"{database_id}.sqlite"
    if candidate.exists():
        return candidate

    directory = root / "database" / database_id
    if directory.is_dir():
        for sqlite_file in sorted(directory.glob("*.sqlite")):
            return sqlite_file

    raise SpiderDatasetError(
        f"No SQLite database for db_id {database_id!r} under {root / 'database'}"
    )


def load_spider_tasks(
    split: str = "dev",
    dataset_root: Path | str = DEFAULT_DATASET_ROOT,
) -> list[SQLTask]:
    """Load one Spider split as `SQLTask` records.

    Raises rather than skipping when a database is missing: a benchmark that
    silently drops tasks reports accuracy over an undocumented subset.
    """
    if split not in SPLIT_FILES:
        raise SpiderDatasetError(
            f"Unknown split {split!r}. Known: {sorted(SPLIT_FILES)}"
        )

    root = Path(dataset_root)
    source = root / SPLIT_FILES[split]
    if not source.exists():
        raise SpiderDatasetError(
            f"Missing {source}. Run: python scripts/download_spider.py"
        )

    rows = json.loads(source.read_text(encoding="utf-8"))
    tasks: list[SQLTask] = []

    for index, row in enumerate(rows):
        database_id = row["db_id"]
        tasks.append(
            SQLTask(
                task_id=f"spider_{split}_{index:04d}",
                question=row["question"],
                database_id=database_id,
                database_path=str(database_path_for(database_id, root)),
                gold_query=row["query"],
                split=split,
                metadata={
                    # Spider's raw JSON has no stable per-row ID of its own, so the
                    # source index is kept as the original task identifier.
                    "source_index": index,
                    "source_file": SPLIT_FILES[split],
                },
            )
        )

    return tasks


def load_gold_file(
    split: str = "dev",
    dataset_root: Path | str = DEFAULT_DATASET_ROOT,
) -> list[tuple[str, str]]:
    """Read `<split>_gold.sql` as `(query, db_id)` pairs.

    Used only to cross-check `dev.json`: if the two disagree, the install is
    corrupt and no benchmark run from it would be trustworthy.
    """
    path = Path(dataset_root) / f"{split}_gold.sql"
    if not path.exists():
        raise SpiderDatasetError(f"Missing gold file {path}")

    pairs: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        query, _, database_id = line.rpartition("\t")
        pairs.append((query.strip(), database_id.strip()))
    return pairs


def verify_split_integrity(
    split: str = "dev",
    dataset_root: Path | str = DEFAULT_DATASET_ROOT,
) -> dict[str, Any]:
    """Check `<split>.json` against `<split>_gold.sql` row for row."""
    tasks = load_spider_tasks(split, dataset_root)
    gold_pairs = load_gold_file(split, dataset_root)

    mismatches: list[dict[str, Any]] = []
    if len(tasks) != len(gold_pairs):
        mismatches.append(
            {
                "kind": "length",
                "json_rows": len(tasks),
                "gold_rows": len(gold_pairs),
            }
        )
    else:
        for task, (gold_query, gold_db) in zip(tasks, gold_pairs):
            if task.database_id != gold_db:
                mismatches.append(
                    {
                        "kind": "db_id",
                        "task_id": task.task_id,
                        "json": task.database_id,
                        "gold": gold_db,
                    }
                )

    return {
        "split": split,
        "tasks": len(tasks),
        "gold_rows": len(gold_pairs),
        "databases": len({task.database_id for task in tasks}),
        "mismatches": mismatches,
        "ok": not mismatches,
    }


def iter_tasks_by_id(tasks: list[SQLTask]) -> Iterator[tuple[str, SQLTask]]:
    for task in tasks:
        yield task.task_id, task
