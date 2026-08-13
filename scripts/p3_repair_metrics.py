"""Shared measurement for the P3 schema-repair experiment.

Every quantity here is recomputed from the persisted tool payloads rather than
read from the episode counters. The counters and the payloads should agree; the
point of not trusting them to is that a counter is written by the same code path
whose behaviour is under test, while the payload is the evidence.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.app.spider.trajectory import open_jsonl

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = REPO_ROOT / "runs" / "support_benchmark"
TOMBSTONE = "QUARANTINE.json"


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open_jsonl(path) as handle:
        return [json.loads(line) for line in handle if line.strip()]


def load_arm(run_ids: list[str], expected_tasks: int) -> tuple[list[dict], list[str]]:
    """Return per-episode records for runs that pass integrity, and the excluded ids."""
    episodes: list[dict] = []
    excluded: list[str] = []
    for run_id in run_ids:
        run_dir = RUN_ROOT / run_id
        if (run_dir / TOMBSTONE).exists():
            excluded.append(f"{run_id} (quarantined)")
            continue
        rows = _read(run_dir / "episodes.jsonl")
        task_ids = [row["task_id"] for row in rows]
        if len(rows) != expected_tasks or len(set(task_ids)) != len(task_ids):
            excluded.append(f"{run_id} ({len(rows)} episodes, "
                            f"{len(task_ids) - len(set(task_ids))} duplicated)")
            continue

        payloads: dict[str, Any] = {}
        for record in _read(run_dir / "payloads.jsonl"):
            payloads[record["ref"]] = record["data"]
        steps: dict[str, list[dict]] = {}
        for step in _read(run_dir / "steps.jsonl"):
            steps.setdefault(step["episode_id"], []).append(step)

        for row in rows:
            episode_steps = sorted(steps.get(row["episode_id"], []),
                                   key=lambda s: s["step_index"])
            invalid_indices: list[int] = []
            tool_calls = 0
            for step in episode_steps:
                if not step.get("tool_name"):
                    continue
                tool_calls += 1
                result = payloads.get(step.get("tool_result_ref")) or {}
                if result.get("validation_error"):
                    invalid_indices.append(step["step_index"])
            episodes.append({
                "run_id": run_id,
                "task_id": row["task_id"],
                "passed": bool((row.get("verification_result") or {}).get("passed")),
                "tool_calls": tool_calls,
                "invalid_calls": len(invalid_indices),
                "invalid_indices": invalid_indices,
                "model_steps": row.get("model_steps", 0),
                "cost": row.get("estimated_cost", 0.0),
                "termination": row.get("termination_reason"),
            })
    return episodes, excluded


def arm_metrics(episodes: list[dict], cohort: set[str] | None = None) -> dict[str, Any]:
    """Primary and secondary metrics exactly as pre-registered."""
    scope = [e for e in episodes if cohort is None or e["task_id"] in cohort]
    if not scope:
        return {"episodes": 0}

    invalid_calls = sum(e["invalid_calls"] for e in scope)
    with_invalid = sum(1 for e in scope if e["invalid_calls"] > 0)
    repeats = invalid_calls - with_invalid  # invalid calls beyond the first

    runs = sorted({e["run_id"] for e in scope})
    per_run = []
    for run_id in runs:
        rows = [e for e in scope if e["run_id"] == run_id]
        calls = sum(e["invalid_calls"] for e in rows)
        firsts = sum(1 for e in rows if e["invalid_calls"] > 0)
        per_run.append({
            "run_id": run_id,
            "repeat_invalid_rate": (calls - firsts) / calls if calls else 0.0,
            "invalid_calls": calls,
            "success": sum(1 for e in rows if e["passed"]) / len(rows),
            "mean_turns": sum(e["model_steps"] for e in rows) / len(rows),
            "mean_cost": sum(e["cost"] for e in rows) / len(rows),
        })

    return {
        "episodes": len(scope),
        "runs": len(runs),
        "invalid_calls": invalid_calls,
        "episodes_with_invalid": with_invalid,
        "episodes_with_two_or_more": sum(1 for e in scope if e["invalid_calls"] >= 2),
        # PRIMARY
        "repeat_invalid_rate": repeats / invalid_calls if invalid_calls else None,
        "degenerate": invalid_calls > 0 and repeats == 0,
        # SECONDARY
        "success": sum(1 for e in scope if e["passed"]) / len(scope),
        "mean_turns": sum(e["model_steps"] for e in scope) / len(scope),
        "mean_cost": sum(e["cost"] for e in scope) / len(scope),
        "tool_calls": sum(e["tool_calls"] for e in scope),
        "per_run": per_run,
    }
