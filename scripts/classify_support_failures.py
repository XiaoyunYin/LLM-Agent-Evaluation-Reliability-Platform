"""Classify calibration failures by their behaviour across repeats.

The point is to separate **benchmark defects from agent weakness** before any
task is frozen. A single failing run cannot tell those apart; repeats can:

| Signature across N repeats | Reading |
|---|---|
| fails every repeat, same missing/undeclared signature | deterministic — spec, verifier, tool or fixture defect until proven otherwise |
| fails every repeat, differing signatures | genuine agent weakness (it tries, it is wrong differently each time) |
| mixed pass/fail | stochastic failure or coherent ambiguity |
| passes every repeat | solved |

Only the first bucket may lead to a task edit, and only under one of the fixed
calibration-edit classes. Poor agent performance is never grounds for an edit.

Usage:
    python -m scripts.classify_support_failures --runs support_hard_1 ... [--task ID]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backend.app.spider.trajectory import open_jsonl  # noqa: E402
from backend.app.support.schema import SCHEMA_VERSION, build_fixture  # noqa: E402
from backend.app.support.tasks import build_tasks  # noqa: E402

RUN_ROOT = REPO_ROOT / "runs" / "support_benchmark"
FIXTURE_PATH = REPO_ROOT / "runs" / "support_benchmark" / "_classify_fixture.db"


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open_jsonl(path) as handle:
        return [json.loads(line) for line in handle if line.strip()]


def load_run(run_id: str) -> tuple[list[dict], dict[str, list[dict]]]:
    run_dir = RUN_ROOT / run_id
    episodes = _read(run_dir / "episodes.jsonl")
    steps_by_episode: dict[str, list[dict]] = defaultdict(list)
    for step in _read(run_dir / "steps.jsonl"):
        steps_by_episode[step["episode_id"]].append(step)
    return episodes, steps_by_episode


def signature(episode: dict) -> str:
    """A compact fingerprint of *how* the episode failed.

    Identical fingerprints across repeats mean the agent is being defeated the
    same way every time, which points at the benchmark rather than the model.
    """
    result = episode.get("verification_result") or {}
    parts = [
        episode.get("termination_reason", "?"),
        result.get("outcome", "?"),
        "missing=" + ",".join(sorted(result.get("missing_required", []))),
        "undeclared=" + ",".join(sorted(result.get("undeclared", []))),
        "no_comment=" + str(len(result.get("missing_comments", []))),
    ]
    return " | ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", nargs="+", required=True)
    parser.add_argument("--task", help="dump full trajectory detail for one task")
    parser.add_argument("--tier", default=None)
    args = parser.parse_args()

    fixture_sha = build_fixture(FIXTURE_PATH)
    suite = {entry["spec"].task_id: entry["spec"]
             for entry in build_tasks(FIXTURE_PATH, fixture_sha, SCHEMA_VERSION)}

    outcomes: dict[str, list[dict]] = defaultdict(list)
    steps: dict[str, dict[str, list[dict]]] = defaultdict(dict)
    for run_id in args.runs:
        episodes, run_steps = load_run(run_id)
        for episode in episodes:
            task_id = episode["task_id"]
            outcomes[task_id].append(episode)
            steps[task_id][run_id] = run_steps.get(episode["episode_id"], [])

    if args.task:
        return dump_task(args.task, suite, outcomes, steps)

    repeats = len(args.runs)
    buckets: dict[str, list[str]] = defaultdict(list)
    for task_id, episodes in sorted(outcomes.items()):
        task = suite.get(task_id)
        if args.tier and task and task.tier != args.tier:
            continue
        passes = sum(1 for e in episodes if (e.get("verification_result") or {}).get("passed"))
        signatures = {signature(e) for e in episodes if not (e.get("verification_result") or {}).get("passed")}
        if passes == len(episodes):
            bucket = "solved"
        elif passes > 0:
            bucket = "intermittent (stochastic or ambiguous)"
        elif len(signatures) == 1:
            bucket = "DETERMINISTIC same-signature (inspect for defect)"
        else:
            bucket = "deterministic, varying signature (agent weakness)"
        buckets[bucket].append(task_id)

    print(f"repeats={repeats}  tasks={sum(len(v) for v in buckets.values())}\n")
    order = [
        "DETERMINISTIC same-signature (inspect for defect)",
        "deterministic, varying signature (agent weakness)",
        "intermittent (stochastic or ambiguous)",
        "solved",
    ]
    for bucket in order:
        task_ids = buckets.get(bucket, [])
        print(f"{bucket}: {len(task_ids)}")
        if bucket == "solved":
            continue
        for task_id in task_ids:
            task = suite.get(task_id)
            family = task.family if task else "?"
            passes = sum(1 for e in outcomes[task_id] if (e.get("verification_result") or {}).get("passed"))
            sigs = {signature(e) for e in outcomes[task_id] if not (e.get("verification_result") or {}).get("passed")}
            print(f"   {task_id:<28} {family:<26} {passes}/{repeats}")
            for sig in sorted(sigs):
                print(f"      {sig}")
        print()
    return 0


def dump_task(task_id, suite, outcomes, steps) -> int:
    task = suite.get(task_id)
    print(f"=== {task_id} ===")
    if task:
        print(f"family={task.family} tier={task.tier} provenance={task.provenance}")
        print(f"attributes={task.attributes.model_dump()}")
        print(f"\nPROMPT:\n{task.prompt}\n")
        print("REQUIRED:")
        for spec in task.required_changes:
            print(f"   {spec.signature()}")
        for predicate in task.required_comments:
            print(f"   comment {predicate.model_dump()}")
        if task.forbidden_changes:
            print("FORBIDDEN:")
            for spec in task.forbidden_changes:
                print(f"   {spec.signature()}")
    for episode in outcomes.get(task_id, []):
        print(f"\n--- run {episode['run_id']} passed={episode.get('passed')} ---")
        print(f"    {signature(episode)}")
        result = episode.get("verification_result") or {}
        print(f"    actual: {result.get('actual_changes', [])}")
        for step in steps[task_id].get(episode["run_id"], []):
            name = step.get("tool_name")
            if not name:
                continue
            arguments = json.dumps(step.get("tool_args", {}), sort_keys=True)
            status = "ok" if step.get("tool_success") else "ERR"
            print(f"    [{step.get('step_index')}] {name}({arguments[:160]}) -> {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
