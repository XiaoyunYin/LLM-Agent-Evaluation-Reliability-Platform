"""Quarantine contaminated runs instead of deleting them.

P2 deleted a contaminated run — 2,042 rows with 1,008 duplicated task IDs from two
concurrent writers. Deleting kept the bad data out of analysis, which was the
point, but it also destroyed the evidence of *how* the contamination happened. The
next occurrence starts the diagnosis from nothing.

So a contaminated run now keeps its directory and gains a `TOMBSTONE.json`. It is
excluded from analysis by the tombstone's presence rather than by its absence from
disk, which is a property tooling can check rather than a fact someone has to
remember.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TOMBSTONE_NAME = "TOMBSTONE.json"

# Detection mechanisms seen so far. Recording which one fired matters: a
# contamination class nothing detects is the dangerous kind.
DETECTION_DUPLICATE_TASK_IDS = "duplicate_task_ids"
DETECTION_EPISODE_COUNT = "unexpected_episode_count"
DETECTION_CONFIG_MISMATCH = "config_mismatch"
DETECTION_INFRASTRUCTURE_EPISODES = "infrastructure_episodes_present"
DETECTION_ORPHAN_PROCESS = "orphan_process_concurrent_writer"
DETECTION_MANUAL = "manual_inspection"


def quarantine(
    run_dir: Path,
    reason: str,
    detection: str,
    evidence: dict[str, Any] | None = None,
) -> Path:
    """Mark a run as contaminated and excluded. Returns the tombstone path."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    tombstone = run_dir / TOMBSTONE_NAME
    tombstone.write_text(
        json.dumps(
            {
                "run_id": run_dir.name,
                "quarantined_at": datetime.now(timezone.utc).isoformat(),
                "contamination_reason": reason,
                "detection_mechanism": detection,
                "exclusion_status": "EXCLUDED_FROM_ALL_ANALYSIS",
                "data_retained": True,
                "why_retained": (
                    "Deleting a contaminated run hides how the contamination "
                    "happened. The data is unusable; the evidence is not."
                ),
                "evidence": evidence or {},
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return tombstone


def is_quarantined(run_dir: Path) -> bool:
    return (Path(run_dir) / TOMBSTONE_NAME).exists()


def tombstone_of(run_dir: Path) -> dict[str, Any] | None:
    path = Path(run_dir) / TOMBSTONE_NAME
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def usable_runs(root: Path, run_ids: list[str]) -> tuple[list[str], list[str]]:
    """Split run IDs into usable and quarantined.

    Analysis scripts call this rather than filtering by hand, so a quarantined run
    cannot be picked up by a script that forgot to check.
    """
    usable, excluded = [], []
    for run_id in run_ids:
        (excluded if is_quarantined(Path(root) / run_id) else usable).append(run_id)
    return usable, excluded
