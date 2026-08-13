"""Verifier QA for the P3 support benchmark. Runs before any agent.

Six checks per task, each targeting a way a state verifier can be wrong:

1. **Reference passes** — replaying the task's own correct action sequence PASSES.
   A task whose reference fails is broken, not hard.
2. **Partial completion fails** — dropping the last required action FAILS.
   Catches a verifier that only checks "something changed".
3. **Unrelated mutation fails** — reference plus a change to a different ticket
   FAILS. Catches a verifier that checks required changes but not undeclared ones.
4. **Wrong-value mutation fails** — the right field set to the wrong value FAILS.
5. **Prohibited extra mutation fails** — where a task declares forbidden changes.
6. **Allowed incidental passes** — where a family permits an incidental comment.

Plus **state isolation**: two episodes from the same fixture must not see each
other's mutations.

Gold-pass alone proves nothing — a verifier hardcoded to PASS scores 100% on
references. Checks 2-5 are the half that catches it.

Usage:
    python scripts/qa_support_verifier.py
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.support.environment import SupportEnvironment  # noqa: E402
from backend.app.support.normalize import NORMALIZATION_VERSION  # noqa: E402
from backend.app.support.schema import (  # noqa: E402
    FIXTURE_VERSION,
    SCHEMA_VERSION,
    build_fixture,
)
from backend.app.support.tasks import TASK_FAMILY_VERSION, build_tasks  # noqa: E402
from backend.app.support.tools import TOOL_DISPATCH, TOOL_SCHEMA_VERSION  # noqa: E402
from backend.app.support.verifier import VERIFIER_VERSION, verify  # noqa: E402

FIXTURE_PATH = REPO_ROOT / "datasets" / "support" / "support_fixture.sqlite"
RESULT_DIR = REPO_ROOT / "runs" / "support_verifier_qa"


def replay(task_spec, actions: list[tuple[str, dict]], workspace: Path) -> Any:
    """Run an action sequence in a fresh episode and verify the resulting state."""
    with SupportEnvironment(FIXTURE_PATH, workspace=workspace) as environment:
        for name, arguments in actions:
            TOOL_DISPATCH[name](environment, dict(arguments))
        changes = environment.state_diff()
        return verify(task_spec, changes, environment.after_state)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickets", type=int, default=60)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    fixture_sha = build_fixture(FIXTURE_PATH, args.tickets)
    tasks = build_tasks(FIXTURE_PATH, fixture_sha, SCHEMA_VERSION)
    workspace = REPO_ROOT / "runs" / "_support_qa_tmp"

    print(f"fixture sha256 {fixture_sha}")
    print(f"tasks generated {len(tasks)}\n")

    checks: list[dict[str, Any]] = []

    def record(task_id: str, name: str, expected: str, result) -> None:
        actual = "PASS" if result.passed else "FAIL"
        checks.append(
            {
                "task_id": task_id,
                "check": name,
                "expected": expected,
                "actual": actual,
                "ok": actual == expected,
                "outcome": result.outcome.value,
                "detail": result.detail,
            }
        )

    # Independent check that no task declares a change the fixture already
    # satisfies. Deliberately recomputed from the fixture rather than trusting the
    # generator's own filter - a generator and its check sharing an assumption is
    # how this class of bug survives.
    import sqlite3

    probe = sqlite3.connect(FIXTURE_PATH)
    probe.row_factory = sqlite3.Row
    fixture_tickets = {
        r["ticket_id"]: dict(r) for r in probe.execute("SELECT * FROM tickets")
    }
    probe.close()

    for entry in tasks:
        spec, reference = entry["spec"], entry["reference"]

        no_ops = [
            f"{c.key}.{c.field}={c.after}"
            for c in spec.required_changes
            if c.kind == "field_changed"
            and c.table == "tickets"
            and str(fixture_tickets.get(c.key, {}).get(c.field)) == str(c.after)
        ]
        checks.append({
            "task_id": spec.task_id, "check": "no_noop_required_changes",
            "expected": "PASS", "actual": "PASS" if not no_ops else "FAIL",
            "ok": not no_ops, "outcome": ",".join(no_ops) or "none",
            "detail": "a required change already true in the fixture is unverifiable",
        })

        record(spec.task_id, "reference_passes", "PASS", replay(spec, reference, workspace))

        if len(reference) > 1:
            record(spec.task_id, "partial_completion_fails", "FAIL",
                   replay(spec, reference[:-1], workspace))

        # Unrelated mutation: touch a ticket the task never mentions.
        other = "TKT-0060" if "TKT-0060" not in str(spec.required_changes) else "TKT-0059"
        record(
            spec.task_id, "unrelated_mutation_fails", "FAIL",
            replay(spec, reference + [("update_ticket", {"ticket_id": other, "priority": "low"})],
                   workspace),
        )

        # Wrong value on a required field.
        wrong = []
        for change in spec.required_changes:
            if change.field == "priority":
                wrong = reference[:-1] + [
                    ("update_ticket", {"ticket_id": change.key, "priority": "low"})
                ]
                break
        if wrong:
            record(spec.task_id, "wrong_value_fails", "FAIL", replay(spec, wrong, workspace))

        if spec.forbidden_changes:
            forbidden = reference + [
                ("update_ticket", {"ticket_id": spec.forbidden_changes[0].key,
                                   "escalated": True})
            ]
            record(spec.task_id, "forbidden_mutation_fails", "FAIL",
                   replay(spec, forbidden, workspace))

        if spec.required_comments:
            missing = [a for a in reference if a[0] != "add_comment"]
            record(spec.task_id, "missing_required_comment_fails", "FAIL",
                   replay(spec, missing, workspace))

    # ---- state isolation --------------------------------------------------
    # Pick a value that genuinely differs, or the probe measures nothing - the
    # first version of this check used a priority TKT-0001 already had and
    # reported a false isolation failure.
    import sqlite3 as _sqlite3

    _probe = _sqlite3.connect(FIXTURE_PATH)
    current_priority = _probe.execute(
        "SELECT priority FROM tickets WHERE ticket_id = 'TKT-0001'"
    ).fetchone()[0]
    _probe.close()
    new_priority = "low" if current_priority != "low" else "high"

    with SupportEnvironment(FIXTURE_PATH, "iso_a", workspace) as a:
        TOOL_DISPATCH["update_ticket"](a, {"ticket_id": "TKT-0001", "priority": new_priority})
        a_diff = len(a.state_diff())
    with SupportEnvironment(FIXTURE_PATH, "iso_b", workspace) as b:
        b_diff = len(b.state_diff())
    isolation_ok = a_diff == 1 and b_diff == 0
    checks.append({
        "task_id": "-", "check": "state_isolation_between_episodes",
        "expected": "PASS", "actual": "PASS" if isolation_ok else "FAIL",
        "ok": isolation_ok, "outcome": f"episode_a_changes={a_diff} episode_b_changes={b_diff}",
        "detail": "a second episode must not observe the first episode's mutations",
    })

    failures = [c for c in checks if not c["ok"]]
    by_check: dict[str, dict[str, int]] = {}
    for check in checks:
        entry = by_check.setdefault(check["check"], {"ok": 0, "bad": 0})
        entry["ok" if check["ok"] else "bad"] += 1

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fixture_sha256": fixture_sha,
        "versions": {
            "schema": SCHEMA_VERSION,
            "fixture": FIXTURE_VERSION,
            "normalization": NORMALIZATION_VERSION,
            "verifier": VERIFIER_VERSION,
            "tools": TOOL_SCHEMA_VERSION,
            "task_families": TASK_FAMILY_VERSION,
        },
        "tasks": len(tasks),
        "checks_run": len(checks),
        "checks_failed": len(failures),
        "by_check": by_check,
        "failures": failures[:40],
        "checks": checks,
    }

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    output = RESULT_DIR / "verifier_qa.json"
    output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print(f"{'check':<36}{'ok':>6}{'bad':>6}")
    for name, counts in sorted(by_check.items()):
        print(f"{name:<36}{counts['ok']:>6}{counts['bad']:>6}")
    print()
    print(f"{len(checks) - len(failures)}/{len(checks)} checks behaved as required")
    if failures:
        print("\nFAILURES:")
        for failure in failures[:15]:
            print(f"  {failure['task_id']} {failure['check']}: "
                  f"expected {failure['expected']} got {failure['actual']} "
                  f"({failure['outcome']}) {failure['detail'][:80]}")
    print(f"\nWrote {output}")

    import shutil
    shutil.rmtree(workspace, ignore_errors=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
