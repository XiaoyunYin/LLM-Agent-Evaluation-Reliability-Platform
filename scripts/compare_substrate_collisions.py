"""Re-evaluate the frozen mutation set on the test-suite substrate.

The question is how much the distilled test suite tightens the metric. Answering it
honestly requires the **same mutations** on both substrates — if each substrate
selected its own set, the collision rates would describe different populations and
the comparison would be meaningless.

So this does not generate mutations. It reads the exact 166 task/mutation pairs
already frozen in the single-database QA artifact (136 detected + 30 collisions) and
re-runs those, and only those, against the test suite.

A **collision** is a mutation whose SQL differs from gold but whose rows are
identical on every instance of the substrate. On one database that is easy; on ~35
distilled instances it is much harder, which is exactly the tightening being
measured.

Usage:
    python scripts/compare_substrate_collisions.py
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.spider.evaluator import (  # noqa: E402
    SUBSTRATE_SINGLE_DB,
    SUBSTRATE_TEST_SUITE,
    VerificationOutcome,
    substrate_database_path,
    verify_sql,
)

FROZEN_QA = REPO_ROOT / "runs" / "spider_verifier_qa" / "verifier_qa_dev.json"
OUTPUT = REPO_ROOT / "runs" / "spider_verifier_qa" / "substrate_collision_comparison.json"


def load_frozen_mutation_set() -> list[dict[str, Any]]:
    """The exact pairs attempted in the frozen single-database QA."""
    report = json.loads(FROZEN_QA.read_text(encoding="utf-8"))
    known_bad = report["known_bad"]

    pairs: list[dict[str, Any]] = []
    for check in known_bad["checks"]:
        pairs.append(
            {
                "mutation": check["mutation"],
                "task_id": check["task_id"],
                "gold_query": check["gold_query"],
                "mutated_query": check["bad_query"],
                "single_db_collision": False,
                "single_db_rejected": check["rejected"],
            }
        )
    for collision in known_bad.get("execution_result_collisions", []):
        pairs.append(
            {
                "mutation": collision["mutation"],
                "task_id": collision["task_id"],
                "gold_query": collision["gold_query"],
                "mutated_query": collision["mutated_query"],
                "single_db_collision": True,
                "single_db_rejected": None,
            }
        )
    return pairs


def _rows(database: Path, query: str) -> list | None:
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True, timeout=30)
    connection.text_factory = lambda value: value.decode(errors="ignore")
    try:
        return sorted(map(str, connection.execute(query).fetchall()))
    except sqlite3.Error:
        return None
    finally:
        connection.close()


def collides_on_substrate(database_id: str, gold: str, mutated: str, substrate: str) -> bool:
    """True when the mutation is indistinguishable from gold on EVERY instance.

    One instance where the rows differ is enough for the substrate to tell them
    apart, which is precisely why more instances collide less.
    """
    anchor = substrate_database_path(database_id, substrate)
    for instance in sorted(anchor.parent.glob("*.sqlite")):
        gold_rows = _rows(instance, gold)
        if gold_rows is None:
            continue  # gold does not run here; that instance cannot discriminate
        mutated_rows = _rows(instance, mutated)
        if mutated_rows is None:
            return False  # mutation errors here, so it is distinguishable
        if gold_rows != mutated_rows:
            return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(OUTPUT))
    args = parser.parse_args()

    if not FROZEN_QA.exists():
        raise SystemExit(f"No frozen single-database QA at {FROZEN_QA}")

    pairs = load_frozen_mutation_set()
    print(f"Frozen mutation set: {len(pairs)} task/mutation pairs\n")

    started = time.perf_counter()
    results: list[dict[str, Any]] = []

    for index, pair in enumerate(pairs, start=1):
        task_id = pair["task_id"]
        database_id = task_id  # placeholder, resolved below
        # The frozen artifact stores the task ID; the database comes from the task.
        from backend.app.spider.loader import load_spider_tasks

        if index == 1:
            tasks = {t.task_id: t for t in load_spider_tasks("dev")}
            main.tasks = tasks  # type: ignore[attr-defined]
        tasks = main.tasks  # type: ignore[attr-defined]
        task = tasks[task_id]
        database_id = task.database_id

        collision = collides_on_substrate(
            database_id, pair["gold_query"], pair["mutated_query"], SUBSTRATE_TEST_SUITE
        )

        rejected = None
        if not collision:
            verification = verify_sql(
                predicted_sql=pair["mutated_query"],
                gold_sql=pair["gold_query"],
                database_path=substrate_database_path(database_id, SUBSTRATE_TEST_SUITE),
                task_id=task_id,
                database_id=database_id,
                substrate=SUBSTRATE_TEST_SUITE,
            )
            rejected = verification.outcome is not VerificationOutcome.PASS

        results.append(
            {
                **pair,
                "database_id": database_id,
                "test_suite_collision": collision,
                "test_suite_rejected": rejected,
            }
        )

        if index % 40 == 0:
            print(f"  {index}/{len(pairs)}")

    attempted = len(results)
    single_collisions = sum(1 for r in results if r["single_db_collision"])
    suite_collisions = sum(1 for r in results if r["test_suite_collision"])
    suite_detected = sum(1 for r in results if r["test_suite_rejected"] is True)
    suite_leaks = [r for r in results if r["test_suite_rejected"] is False]

    # The mutations the test suite newly distinguishes: collided on one database,
    # do not collide across the suite.
    newly_distinguished = [
        r for r in results if r["single_db_collision"] and not r["test_suite_collision"]
    ]
    newly_colliding = [
        r for r in results if not r["single_db_collision"] and r["test_suite_collision"]
    ]

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mutation_set_source": str(FROZEN_QA.relative_to(REPO_ROOT)),
        "mutations_attempted": attempted,
        "identical_set_on_both_substrates": True,
        "single_db": {
            "collisions": single_collisions,
            "collision_rate": single_collisions / attempted,
            "detected": sum(1 for r in results if r["single_db_rejected"] is True),
        },
        "test_suite": {
            "collisions": suite_collisions,
            "collision_rate": suite_collisions / attempted,
            "detected": suite_detected,
            "leaks": len(suite_leaks),
        },
        "collision_rate_reduction_pp": 100
        * (single_collisions - suite_collisions)
        / attempted,
        "newly_distinguished_by_test_suite": {
            "count": len(newly_distinguished),
            "task_ids": sorted({r["task_id"] for r in newly_distinguished}),
        },
        "newly_colliding_on_test_suite": {
            "count": len(newly_colliding),
            "note": (
                "Should be 0 or near it. A mutation distinguishable on one database "
                "but not across the suite would be surprising and worth inspecting."
            ),
            "task_ids": sorted({r["task_id"] for r in newly_colliding}),
        },
        "interpretation": (
            "Collision rate is a property of THIS mutation set on each substrate. "
            "It is not an estimate of the share of the agent's passes that are "
            "false positives on either substrate."
        ),
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "results": results,
    }

    print()
    print(f"{'':<26}{'single-DB':>12}{'test-suite':>12}")
    print(f"{'mutations attempted':<26}{attempted:>12,}{attempted:>12,}")
    print(f"{'collisions':<26}{single_collisions:>12,}{suite_collisions:>12,}")
    print(f"{'collision rate':<26}{single_collisions / attempted:>11.2%}"
          f"{suite_collisions / attempted:>12.2%}")
    print(f"{'detected as wrong':<26}"
          f"{report['single_db']['detected']:>12,}{suite_detected:>12,}")
    print(f"{'leaks':<26}{0:>12,}{len(suite_leaks):>12,}")
    print()
    print(f"collision rate reduction: {report['collision_rate_reduction_pp']:.2f}pp")
    print(f"newly distinguished by the test suite: "
          f"{len(newly_distinguished)} of {single_collisions} single-DB collisions")
    if newly_colliding:
        print(f"WARNING newly colliding on test suite: {len(newly_colliding)}")

    Path(args.output).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
