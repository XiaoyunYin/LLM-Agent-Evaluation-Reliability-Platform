"""Analyze the frozen P3 baseline: task level, tier, family, calls, taxonomy.

Every breakdown here was declared in docs/P3_SUITE_COMPOSITION.md before any
baseline ran, including the failure-taxonomy categories, so nothing about the
framing is chosen after seeing the numbers.

    python -m scripts.analyze_p3_baseline --runs support_base_01 ...
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backend.app.spider.trajectory import open_jsonl  # noqa: E402
from backend.app.support.schema import (  # noqa: E402
    DEFAULT_TICKET_COUNT,
    SCHEMA_VERSION,
    build_fixture,
)
from backend.app.support.tasks import build_tasks  # noqa: E402

RUN_ROOT = REPO_ROOT / "runs" / "support_benchmark"
FIXTURE_PATH = REPO_ROOT / "datasets" / "support" / "support_fixture.sqlite"
RESULT_DIR = REPO_ROOT / "runs" / "support_baseline"

# Frozen before baselines. Order matters: the first matching rule wins, most
# specific first, so a single failure gets exactly one label.
TAXONOMY = (
    "termination_failure",
    "forbidden_mutation_made",
    "wrong_entity",
    "wrong_mutation",
    "incomplete_workflow",
    "undeclared_mutation",
    "no_action_taken",
    "missing_required_comment",
    "correct_actions_verifier_mismatch",
)


def classify(episode: dict, spec) -> str:
    """Assign exactly one frozen taxonomy label to a failed episode."""
    result = episode.get("verification_result") or {}
    if episode.get("termination_reason") not in ("SUCCESS", "VERIFICATION_FAILED"):
        return "termination_failure"

    missing = set(result.get("missing_required", []))
    undeclared = set(result.get("undeclared", []))
    forbidden = set(result.get("forbidden_hit", []))
    actual = set(result.get("actual_changes", []))
    comments = result.get("missing_comments", [])

    if forbidden:
        return "forbidden_mutation_made"
    if missing and not actual:
        return "no_action_taken"

    # Split key and field out of "field_changed:table:key:field:after".
    def parts(signature: str) -> tuple[str, str]:
        chunks = signature.split(":")
        return (chunks[2], chunks[3]) if len(chunks) >= 4 else (chunks[-1], "")

    missing_pairs = {parts(s) for s in missing}
    undeclared_pairs = {parts(s) for s in undeclared}

    if missing:
        # Same field acted on, different entity -> the agent did the right thing
        # to the wrong ticket. Distinguished from a wrong value, which is the
        # right ticket and the wrong content.
        if any(field == m_field and key != m_key
               for (key, field) in undeclared_pairs
               for (m_key, m_field) in missing_pairs):
            return "wrong_entity"
        if any(key == m_key and field == m_field
               for (key, field) in undeclared_pairs
               for (m_key, m_field) in missing_pairs):
            return "wrong_mutation"
        if comments and not missing:
            return "missing_required_comment"
        return "incomplete_workflow"
    if comments:
        return "missing_required_comment"
    if undeclared:
        return "undeclared_mutation"
    return "correct_actions_verifier_mismatch"


def read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open_jsonl(path) as handle:
        return [json.loads(line) for line in handle if line.strip()]


def rate(hits: int, total: int) -> str:
    return f"{hits}/{total} = {hits / total:.3f}" if total else "n/a"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", nargs="+", required=True)
    parser.add_argument("--label", default="baseline")
    args = parser.parse_args()

    fixture_sha = build_fixture(FIXTURE_PATH, DEFAULT_TICKET_COUNT)
    suite = {
        entry["spec"].task_id: entry["spec"]
        for entry in build_tasks(FIXTURE_PATH, fixture_sha, SCHEMA_VERSION)
    }

    per_run: dict[str, list[bool]] = {}
    episodes: list[tuple[str, dict]] = []
    for run_id in args.runs:
        rows = read(RUN_ROOT / run_id / "episodes.jsonl")
        if not rows:
            print(f"!! {run_id} has no episodes")
            continue
        # Integrity: a run must cover the frozen suite exactly once.
        task_ids = [row["task_id"] for row in rows]
        duplicates = [t for t, n in Counter(task_ids).items() if n > 1]
        if duplicates or len(rows) != len(suite):
            print(f"!! {run_id} integrity: {len(rows)} episodes, "
                  f"{len(duplicates)} duplicated task(s) - EXCLUDED")
            continue
        per_run[run_id] = []
        for row in rows:
            passed = bool((row.get("verification_result") or {}).get("passed"))
            per_run[run_id].append(passed)
            episodes.append((run_id, row))

    runs = list(per_run)
    print(f"runs analyzed: {len(runs)}  episodes: {len(episodes)}\n")

    scores = [sum(v) / len(v) for v in per_run.values()]
    print("=== TASK-LEVEL (global) ===")
    for run_id, values in per_run.items():
        print(f"  {run_id:<20} {sum(values)}/{len(values)} = {sum(values) / len(values):.4f}")
    if len(scores) > 1:
        print(f"  mean {statistics.mean(scores):.4f}  sd {statistics.stdev(scores):.4f}  "
              f"min {min(scores):.4f}  max {max(scores):.4f}")

    # ---- tier / family ----------------------------------------------------
    tier: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    family: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    provenance: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    per_task: dict[str, list[bool]] = defaultdict(list)
    for _run_id, row in episodes:
        spec = suite[row["task_id"]]
        passed = bool((row.get("verification_result") or {}).get("passed"))
        for bucket, key in ((tier, spec.tier), (family, spec.family),
                            (provenance, spec.provenance)):
            bucket[key][0] += passed
            bucket[key][1] += 1
        per_task[row["task_id"]].append(passed)

    print("\n=== TIER ===")
    print("  (core = regression canary; hard = pre-declared primary discrimination)")
    for name, (hits, total) in sorted(tier.items()):
        print(f"  {name:<8} {rate(hits, total)}")

    print("\n=== FAMILY ===")
    for name, (hits, total) in sorted(family.items(), key=lambda kv: kv[1][0] / kv[1][1]):
        spec_tier = next(s.tier for s in suite.values() if s.family == name)
        print(f"  {spec_tier:<5} {name:<26} {rate(hits, total)}")

    # ---- consistency ------------------------------------------------------
    n = len(runs)
    print(f"\n=== CONSISTENCY (per-task passes out of {n}) ===")
    print("  ", dict(sorted(Counter(len([p for p in v if p]) for v in per_task.values()).items())))
    always = sum(1 for v in per_task.values() if all(v))
    never = sum(1 for v in per_task.values() if not any(v))
    print(f"  always pass {always}/{len(per_task)}   never pass {never}/{len(per_task)}"
          f"   intermittent {len(per_task) - always - never}/{len(per_task)}")

    # ---- provenance-selection-bias check ----------------------------------
    print("\n=== PROVENANCE (selection-bias check) ===")
    print("  Calibrated tasks were edited; freshly generated ones were not. A large")
    print("  gap would mean editing made tasks easier, i.e. selection bias.")
    for name, (hits, total) in sorted(provenance.items()):
        print(f"  {name:<28} {rate(hits, total)}")

    # ---- call level -------------------------------------------------------
    total_calls = sum(row.get("tool_steps", 0) for _r, row in episodes)
    bad_calls = sum(row.get("bad_argument_tool_calls", 0) for _r, row in episodes)
    bad_episodes = sum(1 for _r, row in episodes if row.get("bad_argument_tool_calls", 0) > 0)
    turns = [row.get("model_steps", 0) for _r, row in episodes]
    cost = sum(row.get("estimated_cost", 0.0) for _r, row in episodes)
    print("\n=== CALL LEVEL ===")
    print(f"  tool calls                {total_calls}")
    print(f"  invalid typed calls       {rate(bad_calls, total_calls)}")
    print(f"  episodes with >=1 invalid {rate(bad_episodes, len(episodes))}")
    print(f"  model turns               median {statistics.median(turns)}  max {max(turns)}")
    print(f"  total cost                ${cost:.4f}  (${cost / len(episodes):.6f}/episode)")

    # ---- frozen failure taxonomy -----------------------------------------
    labels = Counter()
    by_task_label: dict[str, Counter] = defaultdict(Counter)
    for _run_id, row in episodes:
        if bool((row.get("verification_result") or {}).get("passed")):
            continue
        label = classify(row, suite[row["task_id"]])
        labels[label] += 1
        by_task_label[row["task_id"]][label] += 1
    failures = sum(labels.values())
    print(f"\n=== FROZEN FAILURE TAXONOMY ({failures} failures) ===")
    for label in TAXONOMY:
        if labels[label]:
            print(f"  {label:<36} {labels[label]:>4}  ({labels[label] / failures:.1%})")
    unknown = set(labels) - set(TAXONOMY)
    for label in sorted(unknown):
        print(f"  !! UNLISTED {label:<24} {labels[label]:>4}")

    print("\n  failing tasks:")
    for task_id, counts in sorted(by_task_label.items(),
                                  key=lambda kv: -sum(kv[1].values())):
        spec = suite[task_id]
        print(f"    {task_id:<24} {spec.family:<26} "
              f"{sum(counts.values())}/{n}  {dict(counts)}")

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "label": args.label,
        "runs": runs,
        "episodes": len(episodes),
        "per_run_success": {k: sum(v) / len(v) for k, v in per_run.items()},
        "mean_success": statistics.mean(scores) if scores else None,
        "sd_success": statistics.stdev(scores) if len(scores) > 1 else None,
        "tier": {k: {"passed": v[0], "total": v[1]} for k, v in tier.items()},
        "family": {k: {"passed": v[0], "total": v[1]} for k, v in family.items()},
        "provenance": {k: {"passed": v[0], "total": v[1]} for k, v in provenance.items()},
        "consistency": {"always": always, "never": never,
                        "intermittent": len(per_task) - always - never},
        "calls": {"tool_calls": total_calls, "invalid_calls": bad_calls,
                  "episodes_with_invalid": bad_episodes, "episodes": len(episodes)},
        "cost_usd": cost,
        "taxonomy": dict(labels),
        "failing_tasks": {k: dict(v) for k, v in by_task_label.items()},
    }
    output = RESULT_DIR / f"{args.label}.json"
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nWrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
