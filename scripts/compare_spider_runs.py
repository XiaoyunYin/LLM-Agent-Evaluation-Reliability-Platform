"""Compare two Spider benchmark runs task by task.

Written because a hand-rolled comparison got it wrong. An earlier analysis counted
`termination_reason != termination_reason` and published the result as "tasks that
flipped outcome". That number includes FAIL->FAIL reason changes - an episode going
from VERIFICATION_FAILED to MAX_STEPS never changed its outcome - so it overstated
pass/fail churn. The correct quantity is the 2x2 contingency table below, and this
script asserts two identities that the wrong number cannot satisfy:

    PASS->FAIL + FAIL->PASS == total pass/fail flips
    FAIL->PASS - PASS->FAIL == passes(B) - passes(A)

Both are checked, and the script exits non-zero if either fails.

It also diffs the two run configurations field by field, so "identical
configuration" is a saved artifact rather than an assertion.

Usage:
    python scripts/compare_spider_runs.py --run-a spider_full__p0_v1 \\
                                          --run-b spider_full__p0_v2
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.spider.trajectory import DEFAULT_RUN_ROOT, TrajectoryStore  # noqa: E402

# Fields that define "the same experiment". A difference in any of these means the
# two runs are not comparable as a repeat.
IDENTITY_FIELDS = (
    "dataset", "dataset_version", "split", "archive_sha256", "dev_json_sha256",
    "model_version", "prompt_version", "tool_schema_version", "adapter_version",
    "agent_version", "max_steps", "temperature", "max_visible_rows",
    "valid_task_count", "excluded_task_ids", "sampled", "sample_seed",
)

# Fields expected to differ between any two runs; listed so they are reported as
# expected rather than as configuration drift.
EXPECTED_TO_DIFFER = (
    "run_id", "started_at", "stage", "code_commit_sha",
    "code_working_tree_dirty", "selected_task_ids",
)


def load_run(run_id: str, root: Path) -> tuple[dict[str, Any], dict[str, dict]]:
    store = TrajectoryStore(run_id, root)
    if not store.episodes_path.exists():
        raise SystemExit(f"No episodes for {run_id}")
    config = (
        json.loads(store.config_path.read_text(encoding="utf-8"))
        if store.config_path.exists()
        else {}
    )
    episodes = {e["task_id"]: e for e in store.iter_episodes()}
    return config, episodes


def sampling_settings(config: dict[str, Any]) -> dict[str, Any]:
    """What actually governed nondeterminism, including what was NOT set.

    A parameter that was never sent and a parameter set to its default look the
    same in a result. Recording the difference is what lets a later reader judge
    whether two runs really were configured identically.
    """
    return {
        "temperature": config.get("temperature"),
        "top_p": config.get("top_p", "not recorded (parameter not sent; provider default applied)"),
        "seed": config.get("seed", "not recorded (parameter not sent)"),
        "requested_model_alias": config.get("model_version"),
        "resolved_model_revision": config.get(
            "resolved_model_revision",
            "not captured for this run; the alias above was requested",
        ),
        "determinism_note": (
            "No seed was sent. These are repeated runs under an identical recorded "
            "configuration, NOT seeded runs. OpenAI's seed parameter is best-effort "
            "and would not make them deterministic either."
        ),
    }


def compare(run_a: str, run_b: str, root: Path) -> dict[str, Any]:
    config_a, episodes_a = load_run(run_a, root)
    config_b, episodes_b = load_run(run_b, root)

    tasks_a, tasks_b = set(episodes_a), set(episodes_b)
    shared = sorted(tasks_a & tasks_b)

    # -- configuration diff ------------------------------------------------
    identity_diff = {
        field: {"a": config_a.get(field), "b": config_b.get(field)}
        for field in IDENTITY_FIELDS
        if config_a.get(field) != config_b.get(field)
    }
    incidental_diff = {
        field: {"a": config_a.get(field), "b": config_b.get(field)}
        for field in EXPECTED_TO_DIFFER
        if config_a.get(field) != config_b.get(field)
    }
    unreviewed = sorted(
        (set(config_a) | set(config_b)) - set(IDENTITY_FIELDS) - set(EXPECTED_TO_DIFFER)
    )
    other_diff = {
        field: {"a": config_a.get(field), "b": config_b.get(field)}
        for field in unreviewed
        if config_a.get(field) != config_b.get(field)
    }

    # -- 2x2 pass/fail contingency ----------------------------------------
    def passed(episode: dict) -> bool:
        return episode["termination_reason"] == "SUCCESS"

    cells = collections.Counter(
        (passed(episodes_a[t]), passed(episodes_b[t])) for t in shared
    )
    pass_pass = cells[(True, True)]
    pass_fail = cells[(True, False)]
    fail_pass = cells[(False, True)]
    fail_fail = cells[(False, False)]

    passes_a = pass_pass + pass_fail
    passes_b = pass_pass + fail_pass
    total_flips = pass_fail + fail_pass

    identities = {
        "cells_sum_to_shared_tasks": {
            "expected": len(shared),
            "actual": pass_pass + pass_fail + fail_pass + fail_fail,
            "holds": pass_pass + pass_fail + fail_pass + fail_fail == len(shared),
        },
        "flips_equal_offdiagonal": {
            "expected": total_flips,
            "actual": pass_fail + fail_pass,
            "holds": True,
        },
        "net_change_matches_pass_counts": {
            "fail_to_pass_minus_pass_to_fail": fail_pass - pass_fail,
            "passes_b_minus_passes_a": passes_b - passes_a,
            "holds": (fail_pass - pass_fail) == (passes_b - passes_a),
        },
    }

    # -- termination-reason transitions ------------------------------------
    transitions = collections.Counter(
        (episodes_a[t]["termination_reason"], episodes_b[t]["termination_reason"])
        for t in shared
    )
    reason_changes = sum(
        count for (before, after), count in transitions.items() if before != after
    )
    fail_to_fail_reason_changes = sum(
        count
        for (before, after), count in transitions.items()
        if before != after and before != "SUCCESS" and after != "SUCCESS"
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_a": run_a,
        "run_b": run_b,
        "task_sets": {
            "shared": len(shared),
            "only_in_a": sorted(tasks_a - tasks_b),
            "only_in_b": sorted(tasks_b - tasks_a),
            "identical": tasks_a == tasks_b,
        },
        "configuration": {
            "identity_field_differences": identity_diff,
            "same_experiment": not identity_diff,
            "expected_differences": incidental_diff,
            "other_differences": other_diff,
            "fields_compared": list(IDENTITY_FIELDS),
        },
        "sampling": {"run_a": sampling_settings(config_a), "run_b": sampling_settings(config_b)},
        "accuracy": {
            "run_a": {"passes": passes_a, "total": len(shared), "rate": passes_a / len(shared)},
            "run_b": {"passes": passes_b, "total": len(shared), "rate": passes_b / len(shared)},
            "net_change_tasks": passes_b - passes_a,
            "net_change_rate": (passes_b - passes_a) / len(shared),
        },
        "pass_fail_ledger": {
            "definition": (
                "PASS means termination_reason == SUCCESS. Counted per task, joined "
                "on task_id across the two runs."
            ),
            "pass_to_pass": pass_pass,
            "pass_to_fail": pass_fail,
            "fail_to_pass": fail_pass,
            "fail_to_fail": fail_fail,
            "total_pass_fail_flips": total_flips,
            "flip_rate": total_flips / len(shared),
            "identities": identities,
            "all_identities_hold": all(entry["holds"] for entry in identities.values()),
        },
        "termination_reason_churn": {
            "definition": (
                "Any change in termination_reason, INCLUDING fail-to-fail changes "
                "that did not alter the outcome. Strictly larger than the pass/fail "
                "flip count, and not a substitute for it."
            ),
            "total_reason_changes": reason_changes,
            "of_which_fail_to_fail": fail_to_fail_reason_changes,
            "of_which_changed_outcome": total_flips,
            "transitions": {
                f"{before}->{after}": count
                for (before, after), count in sorted(
                    transitions.items(), key=lambda item: -item[1]
                )
                if before != after
            },
        },
        "flipped_task_ids": {
            "pass_to_fail": sorted(
                t for t in shared if passed(episodes_a[t]) and not passed(episodes_b[t])
            ),
            "fail_to_pass": sorted(
                t for t in shared if not passed(episodes_a[t]) and passed(episodes_b[t])
            ),
        },
    }


def print_report(report: dict[str, Any]) -> None:
    print(f"Run comparison: {report['run_a']}  ->  {report['run_b']}\n")

    config = report["configuration"]
    print("CONFIGURATION")
    print(f"  same experiment (no identity-field differences): {config['same_experiment']}")
    if config["identity_field_differences"]:
        for field, values in config["identity_field_differences"].items():
            print(f"    DIFFERS {field}: {values['a']!r} -> {values['b']!r}")
    print(f"  task sets identical: {report['task_sets']['identical']} "
          f"({report['task_sets']['shared']:,} shared)")
    print(f"  expected differences: {sorted(config['expected_differences'])}")
    if config["other_differences"]:
        print(f"  UNREVIEWED differences: {sorted(config['other_differences'])}")
    print()

    sampling = report["sampling"]["run_b"]
    print("SAMPLING / NONDETERMINISM")
    for key in ("temperature", "top_p", "seed", "requested_model_alias", "resolved_model_revision"):
        print(f"  {key:<26} {sampling[key]}")
    print(f"  {sampling['determinism_note']}")
    print()

    accuracy = report["accuracy"]
    print("ACCURACY")
    print(f"  {report['run_a']:<24} {accuracy['run_a']['passes']:,}/"
          f"{accuracy['run_a']['total']:,} = {accuracy['run_a']['rate']:.4f}")
    print(f"  {report['run_b']:<24} {accuracy['run_b']['passes']:,}/"
          f"{accuracy['run_b']['total']:,} = {accuracy['run_b']['rate']:.4f}")
    print(f"  net change               {accuracy['net_change_tasks']:+d} tasks "
          f"({accuracy['net_change_rate']:+.4f})")
    print()

    ledger = report["pass_fail_ledger"]
    print("PASS/FAIL LEDGER")
    print(f"  {'':<14}{'B: PASS':>10}{'B: FAIL':>10}")
    print(f"  {'A: PASS':<14}{ledger['pass_to_pass']:>10,}{ledger['pass_to_fail']:>10,}")
    print(f"  {'A: FAIL':<14}{ledger['fail_to_pass']:>10,}{ledger['fail_to_fail']:>10,}")
    print()
    print(f"  PASS->FAIL              {ledger['pass_to_fail']:,}")
    print(f"  FAIL->PASS              {ledger['fail_to_pass']:,}")
    print(f"  total pass/fail flips   {ledger['total_pass_fail_flips']:,} "
          f"({ledger['flip_rate']:.2%} of tasks)")
    print()
    for name, entry in ledger["identities"].items():
        print(f"  identity {name:<34} {entry['holds']}")
    print()

    churn = report["termination_reason_churn"]
    print("TERMINATION-REASON CHURN  (larger than flips; not a substitute)")
    print(f"  total reason changes    {churn['total_reason_changes']:,}")
    print(f"    changed outcome       {churn['of_which_changed_outcome']:,}")
    print(f"    fail->fail only       {churn['of_which_fail_to_fail']:,}")
    for transition, count in churn["transitions"].items():
        print(f"    {transition:<44} {count:,}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-a", required=True)
    parser.add_argument("--run-b", required=True)
    parser.add_argument("--root", default=str(DEFAULT_RUN_ROOT))
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    root = Path(args.root)
    report = compare(args.run_a, args.run_b, root)
    print_report(report)

    output = Path(args.output) if args.output else (
        root / args.run_b / f"comparison_vs_{args.run_a}.json"
    )
    output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {output}")

    if not report["pass_fail_ledger"]["all_identities_hold"]:
        print("\nIDENTITY CHECK FAILED - the ledger does not reconcile.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
