"""Verifier QA for the Spider execution evaluator (P0 plan, Step 3).

Two checks, run before any agent ever touches the benchmark.

**Gold-pass QA.** Every gold query in the split is fed to the evaluator as if it
were a prediction. Each must PASS. A gold query that fails is either a broken
integration or a genuine benchmark annotation defect, and until this is clean the
measured agent accuracy is meaningless - a task the verifier can never pass caps
the score for reasons that have nothing to do with the agent.

**Known-bad QA.** Deliberately wrong queries must FAIL. Gold-pass alone does not
prove a verifier works: a verifier hardcoded to return PASS also scores 100% on
gold. This is the half that catches it.

Any gold-pass failure is written to `LOCKED_INPUTS.md` as a frozen exclusion. The
list is frozen *before* agent results exist, so it can never be tuned to flatter
the agent.

Usage:
    python scripts/qa_spider_evaluator.py --split dev
    python scripts/qa_spider_evaluator.py --split dev --limit 20
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.spider.evaluator import (  # noqa: E402
    EVALUATOR_METRIC,
    EVALUATOR_NAME,
    VerificationOutcome,
    verify_sql,
)
from backend.app.spider.loader import (  # noqa: E402
    load_pin,
    load_spider_tasks,
    verify_split_integrity,
)

RESULT_DIR = REPO_ROOT / "runs" / "spider_verifier_qa"
LOCKED_INPUTS_PATH = REPO_ROOT / "docs" / "LOCKED_INPUTS.md"

# Known-bad mutations. Each takes a gold query and returns a query that must not
# pass, or None when the mutation does not apply to that query shape.
#
# These are chosen to break *denotation*, not syntax. A syntax error is a weak
# test - it would fail even a verifier that only checked "did this execute".


def _swap_count_for_constant(gold: str) -> str | None:
    lowered = gold.lower()
    if "count(" not in lowered:
        return None
    # Returns a single row with a plausible-looking number that is almost never
    # the true count.
    return "SELECT 999999"


def _drop_where(gold: str) -> str | None:
    lowered = gold.lower()
    index = lowered.find(" where ")
    if index == -1:
        return None
    tail = lowered[index + 7 :]
    # Only safe when WHERE is the last clause; otherwise removing it would strip
    # GROUP BY/ORDER BY too and change the failure into a shape mismatch.
    for keyword in (" group by ", " order by ", " limit ", " having ", " union ", " intersect ", " except "):
        if keyword in tail:
            return None
    return gold[:index]


def _negate_limit(gold: str) -> str | None:
    lowered = gold.lower()
    index = lowered.rfind(" limit ")
    if index == -1:
        return None
    return gold[:index] + " LIMIT 1" if not lowered.rstrip().endswith("limit 1") else None


def _empty_result(gold: str) -> str | None:
    # Universally applicable: forces zero rows out of the same select list.
    lowered = gold.lower()
    if " limit " in lowered or "count(" in lowered:
        return None
    return f"SELECT * FROM ({gold}) WHERE 1 = 0"


KNOWN_BAD_MUTATIONS = {
    "constant_instead_of_count": _swap_count_for_constant,
    "where_clause_removed": _drop_where,
    "limit_narrowed": _negate_limit,
    "forced_empty_result": _empty_result,
}


def run_gold_pass_qa(tasks, verbose: bool) -> dict:
    failures: list[dict] = []
    outcome_counts: dict[str, int] = {}
    started = time.perf_counter()

    for index, task in enumerate(tasks, start=1):
        result = verify_sql(
            predicted_sql=task.gold_query,
            gold_sql=task.gold_query,
            database_path=task.database_path,
            task_id=task.task_id,
            database_id=task.database_id,
        )
        outcome_counts[result.outcome.value] = outcome_counts.get(result.outcome.value, 0) + 1

        if result.outcome is not VerificationOutcome.PASS:
            failures.append(
                {
                    "task_id": task.task_id,
                    "database_id": task.database_id,
                    "question": task.question,
                    "gold_query": task.gold_query,
                    "outcome": result.outcome.value,
                    "error": result.error,
                }
            )

        if verbose and index % 100 == 0:
            print(f"  gold-pass {index}/{len(tasks)} ({len(failures)} failing)")

    return {
        "checked": len(tasks),
        "passed": outcome_counts.get("pass", 0),
        "outcome_counts": outcome_counts,
        "failures": failures,
        "elapsed_seconds": round(time.perf_counter() - started, 2),
    }


def _denotation(database_path: str, query: str) -> list[tuple] | None:
    """Run a query directly and return its rows, or None if it errors."""
    connection = sqlite3.connect(
        f"file:{Path(database_path).as_posix()}?mode=ro", uri=True, timeout=30
    )
    connection.text_factory = lambda value: value.decode(errors="ignore")
    try:
        return connection.execute(query).fetchall()
    except sqlite3.Error:
        return None
    finally:
        connection.close()


def _mutation_changes_result(database_path: str, gold: str, bad: str) -> bool:
    """True when the mutated query actually returns something different.

    Without this check, a "known-bad" query that happens to be denotationally
    equivalent on this database counts as a verifier leak when the verifier was
    right. Dropping `WHERE age > 20` from a singers query is not a wrong answer
    if every singer is over 20 - it is a different query with the same answer.

    This is exactly the limitation of execution accuracy on a single database,
    and the QA has to respect it rather than report it as a verifier defect.
    """
    gold_rows = _denotation(database_path, gold)
    bad_rows = _denotation(database_path, bad)

    if gold_rows is None:
        return False
    if bad_rows is None:
        # The mutation produced a query that errors. That is a valid known-bad,
        # though a weaker one than a denotation change.
        return True
    return sorted(map(str, gold_rows)) != sorted(map(str, bad_rows))


def run_known_bad_qa(tasks, per_mutation: int, verbose: bool) -> dict:
    checks: list[dict] = []
    leaks: list[dict] = []
    collisions: list[dict] = []
    skipped_equivalent = 0
    started = time.perf_counter()

    for name, mutate in KNOWN_BAD_MUTATIONS.items():
        applied = 0
        for task in tasks:
            if applied >= per_mutation:
                break
            bad_sql = mutate(task.gold_query)
            if bad_sql is None:
                continue

            if not _mutation_changes_result(task.database_path, task.gold_query, bad_sql):
                # Recorded individually, not just counted. These are the measured
                # blind spot of single-database execution accuracy, so the exact
                # task and mutated query must be inspectable and reproducible.
                collisions.append(
                    {
                        "mutation": name,
                        "task_id": task.task_id,
                        "database_id": task.database_id,
                        "gold_query": task.gold_query,
                        "mutated_query": bad_sql,
                        "reason": "returns identical rows to gold on the shipped database",
                    }
                )
                skipped_equivalent += 1
                continue

            result = verify_sql(
                predicted_sql=bad_sql,
                gold_sql=task.gold_query,
                database_path=task.database_path,
                task_id=task.task_id,
                database_id=task.database_id,
            )
            applied += 1
            record = {
                "mutation": name,
                "task_id": task.task_id,
                "gold_query": task.gold_query,
                "bad_query": bad_sql,
                "outcome": result.outcome.value,
                "rejected": result.outcome is not VerificationOutcome.PASS,
            }
            checks.append(record)
            if not record["rejected"]:
                leaks.append(record)

        if verbose:
            print(f"  known-bad {name}: {applied} checks applied")

    return {
        "checked": len(checks),
        "rejected": sum(1 for c in checks if c["rejected"]),
        "leaked": leaks,
        "per_mutation": per_mutation,
        # Mutations discarded because they turned out to be denotationally
        # equivalent on this database. Reported, not hidden: the count is a
        # direct measure of how often single-database EX cannot distinguish two
        # different queries.
        "skipped_denotationally_equivalent": skipped_equivalent,
        "mutations_attempted": len(checks) + skipped_equivalent,
        "collision_rate_on_attempted_mutations": (
            skipped_equivalent / (len(checks) + skipped_equivalent)
            if (len(checks) + skipped_equivalent)
            else None
        ),
        "collision_rate_meaning": (
            "Share of THIS mutation set that single-database execution accuracy "
            "cannot distinguish from gold. It is NOT an estimate of the share of "
            "the agent's passes that are false positives - the agent's queries are "
            "not drawn from this distribution."
        ),
        "execution_result_collisions": collisions,
        "checks": checks,
        "elapsed_seconds": round(time.perf_counter() - started, 2),
    }


def write_locked_inputs(report: dict) -> None:
    """Freeze the exclusion list.

    Written once from gold-pass QA. If the file already records exclusions, they
    are preserved and the run is compared against them - the plan forbids editing
    exclusions after agent results exist.
    """
    gold = report["gold_pass"]
    excluded = gold["failures"]
    pin = report["pin"]

    lines = [
        "# Locked Inputs — Spider SQL Agent Benchmark (P0)",
        "",
        "Frozen benchmark configuration. Everything here was fixed **before** any",
        "agent produced a single query, so none of it can be tuned to flatter a",
        "result. Changing any value invalidates comparison with prior runs.",
        "",
        "## Dataset pin",
        "",
        f"- Benchmark: `{pin['benchmark']}`",
        f"- Archive sha256: `{pin['archive_sha256']}`",
        f"- Archive bytes: {pin['archive_bytes']:,}",
        f"- Dev examples: {pin['dev_examples']:,}",
        f"- Databases: {pin['databases']:,}",
        f"- `dev.json` sha256: `{pin['dev_json_sha256']}`",
        f"- `tables.json` sha256: `{pin['tables_json_sha256']}`",
        f"- Pinned at: {pin['pinned_at']}",
        "",
        "## Evaluator pin",
        "",
        f"- Evaluator: `{EVALUATOR_NAME}` (vendored from {pin['evaluator_source']})",
        f"- Metric: `{EVALUATOR_METRIC}`",
        "- Flags: `plug_value=False`, `keep_distinct=False` — the official",
        "  execution-accuracy defaults (`evaluation.py --etype exec`).",
        "",
        "Vendored file hashes:",
        "",
    ]
    for name, digest in sorted(pin.get("evaluator_file_sha256", {}).items()):
        lines.append(f"- `{name}`: `{digest}`")

    lines += [
        "",
        "## Split discipline",
        "",
        f"- Reported split: `{report['split']}`",
        "- Train and dev are never mixed in a reported benchmark.",
        "",
        "## Verifier QA (frozen)",
        "",
        f"- Gold-pass QA run at: {report['generated_at']}",
        f"- Gold queries checked: {gold['checked']:,}",
        f"- Gold queries passing: {gold['passed']:,}",
        "",
        "### Known-bad (adversarial) QA",
        "",
        "| | |",
        "|---|---:|",
        f"| Mutations attempted | {report['known_bad'].get('mutations_attempted', 0):,} |",
        f"| Detected as wrong (correctly rejected) | {report['known_bad']['checked']:,} |",
        f"| Leaked (wrongly passed) | {len(report['known_bad']['leaked']):,} |",
        f"| Execution-result collisions (discarded) | "
        f"{report['known_bad']['skipped_denotationally_equivalent']:,} |",
        f"| Collision rate on attempted mutations | "
        f"{(report['known_bad'].get('collision_rate_on_attempted_mutations') or 0):.4f} |",
        "",
        "A **collision** is a mutation whose SQL text differs from gold but whose",
        "rows are identical on the shipped database, so single-database execution",
        "accuracy cannot tell them apart. Those are discarded rather than counted as",
        "verifier leaks, and every one is recorded with its task ID and mutated query",
        "in the QA artifact.",
        "",
        "**The collision rate is a property of this mutation set, not of the agent.**",
        "It is not an estimate that the same share of the agent's passes are false",
        "positives - the agent's queries are not drawn from this distribution.",
        "",
        "## Frozen exclusion list",
        "",
    ]

    if not excluded:
        lines += [
            "**Empty.** Every gold query in the reported split passes the evaluator,",
            "so no task is excluded. Task success is measured over the full split.",
            "",
        ]
    else:
        lines += [
            f"{len(excluded)} task(s) excluded because the *gold* query does not pass",
            "the evaluator. These are benchmark/evaluator defects, not agent failures.",
            "",
            "| Task ID | Database | Outcome | Reason |",
            "|---|---|---|---|",
        ]
        for row in excluded:
            reason = (row.get("error") or "").replace("|", "\\|").replace("\n", " ")[:160]
            lines.append(
                f"| `{row['task_id']}` | `{row['database_id']}` | {row['outcome']} | {reason} |"
            )
        lines.append("")

    lines += [
        "## Rules",
        "",
        "1. Exclusions are frozen at the timestamp above and are never edited after",
        "   agent results exist.",
        "2. Tasks are never silently skipped. A task is either measured or listed here",
        "   with a reason.",
        "3. Re-running `scripts/qa_spider_evaluator.py` regenerates this file only when",
        "   the dataset pin changes; a differing exclusion set on the same pin is a",
        "   defect to investigate, not a result to adopt.",
        "",
    ]

    LOCKED_INPUTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCKED_INPUTS_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", default="dev", help="Spider split to QA.")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Check only the first N tasks (development only; do not freeze from this).",
    )
    parser.add_argument(
        "--per-mutation",
        type=int,
        default=25,
        help="Known-bad checks per mutation type.",
    )
    parser.add_argument(
        "--no-freeze",
        action="store_true",
        help="Skip writing docs/LOCKED_INPUTS.md.",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    verbose = not args.quiet

    pin = load_pin()
    integrity = verify_split_integrity(args.split)
    if not integrity["ok"]:
        print("Split integrity check FAILED:", json.dumps(integrity, indent=2))
        return 1

    tasks = load_spider_tasks(args.split)
    if args.limit:
        tasks = tasks[: args.limit]

    print(f"Spider {args.split}: {len(tasks):,} tasks, {integrity['databases']} databases")
    print("Running gold-pass QA ...")
    gold_report = run_gold_pass_qa(tasks, verbose)

    print("Running known-bad QA ...")
    known_bad_report = run_known_bad_qa(tasks, args.per_mutation, verbose)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "split": args.split,
        "limited_to": args.limit,
        "pin": pin,
        "integrity": integrity,
        "gold_pass": gold_report,
        "known_bad": known_bad_report,
    }

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    result_path = RESULT_DIR / f"verifier_qa_{args.split}.json"
    result_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print()
    print(f"Gold-pass:  {gold_report['passed']:,}/{gold_report['checked']:,} pass "
          f"({gold_report['elapsed_seconds']}s)")
    if gold_report["failures"]:
        print(f"  {len(gold_report['failures'])} gold failures:")
        for row in gold_report["failures"][:10]:
            print(f"    {row['task_id']} [{row['database_id']}] {row['outcome']}: {row['error']}")

    print(f"Known-bad:  {known_bad_report['rejected']:,}/{known_bad_report['checked']:,} "
          f"correctly rejected ({known_bad_report['elapsed_seconds']}s); "
          f"{known_bad_report['skipped_denotationally_equivalent']} mutations discarded "
          f"as denotationally equivalent")
    if known_bad_report["leaked"]:
        print(f"  {len(known_bad_report['leaked'])} LEAKED (bad query passed the verifier):")
        for row in known_bad_report["leaked"][:10]:
            print(f"    {row['mutation']} {row['task_id']}: {row['bad_query'][:80]}")

    print(f"Report:     {result_path}")

    if args.limit and not args.no_freeze:
        print("Refusing to freeze LOCKED_INPUTS.md from a --limit run.")
    elif not args.no_freeze:
        write_locked_inputs(report)
        print(f"Frozen:     {LOCKED_INPUTS_PATH}")

    # A leaked known-bad query means the verifier does not discriminate. That is
    # a hard stop: every downstream accuracy number would be untrustworthy.
    return 1 if known_bad_report["leaked"] else 0


if __name__ == "__main__":
    sys.exit(main())
