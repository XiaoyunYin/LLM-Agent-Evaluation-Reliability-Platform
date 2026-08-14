"""Run the deterministic P4a crash-safety matrix.

This is deliberately model-free. It replays P3 reference trajectories through the
P4a durability protocol, injects every supported crash window at every effectful
step, verifies final state with the P3 verifier, and writes a raw JSON artifact.

Usage:
    python -m scripts.run_p4a_matrix --run-id p4a_matrix_dev
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.support.durability import (  # noqa: E402
    CrashInjection,
    CrashWindow,
    DeterministicP4Runner,
    EffectStore,
    P4Crash,
    RunnerStore,
    verify_invariants,
)
from backend.app.support.environment import SupportEnvironment  # noqa: E402
from backend.app.support.normalize import NORMALIZATION_VERSION  # noqa: E402
from backend.app.support.schema import (  # noqa: E402
    DEFAULT_TICKET_COUNT,
    SCHEMA_VERSION,
    build_fixture,
)
from backend.app.support.tasks import TASK_FAMILY_VERSION, build_tasks  # noqa: E402
from backend.app.support.tools import EFFECTFUL_TOOLS, TOOL_SCHEMA_VERSION  # noqa: E402
from backend.app.support.verifier import VERIFIER_VERSION, verify  # noqa: E402

FIXTURE_PATH = REPO_ROOT / "datasets" / "support" / "support_fixture.sqlite"
MANIFEST_PATH = REPO_ROOT / "config" / "p3_frozen_manifest.json"
RUN_ROOT = REPO_ROOT / "runs" / "p4a_matrix"


@dataclass(frozen=True)
class MatrixCase:
    case_id: str
    task_id: str
    family: str
    tier: str
    crash_window: str | None
    step_index: int | None
    tool_name: str | None
    trajectory_length: int


def selected_entries(task_ids: set[str] | None) -> list[dict[str, Any]]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    fixture_sha = manifest["fixture_sha256"]
    # The fixture is deliberately not committed: it is generated deterministically
    # from a seed, and the manifest hash is the record of what it must be. Requiring
    # the file to pre-exist made the repo unbuildable from a clean checkout, which
    # is exactly what CI does - so build it when absent, then verify it byte for
    # byte against the frozen hash. Generating it is not trusting it.
    if not FIXTURE_PATH.exists():
        built_sha = build_fixture(FIXTURE_PATH, DEFAULT_TICKET_COUNT)
        if built_sha != fixture_sha:
            raise RuntimeError(
                f"regenerated fixture hash {built_sha} does not match the frozen "
                f"manifest hash {fixture_sha}. The generator and the freeze have "
                "diverged; do not run against it."
            )
    entries = build_tasks(FIXTURE_PATH, fixture_sha, SCHEMA_VERSION)
    if task_ids is None:
        return entries
    selected = [entry for entry in entries if entry["spec"].task_id in task_ids]
    missing = sorted(task_ids - {entry["spec"].task_id for entry in selected})
    if missing:
        raise ValueError(f"unknown task ids: {missing}")
    return selected


def enumerate_cases(entries: list[dict[str, Any]]) -> list[tuple[MatrixCase, dict[str, Any]]]:
    cases: list[tuple[MatrixCase, dict[str, Any]]] = []
    for entry in entries:
        spec = entry["spec"]
        reference = entry["reference"]
        cases.append((
            MatrixCase(
                case_id=f"{spec.task_id}__clean",
                task_id=spec.task_id,
                family=spec.family,
                tier=spec.tier,
                crash_window=None,
                step_index=None,
                tool_name=None,
                trajectory_length=len(reference),
            ),
            entry,
        ))
        for step_index, (tool_name, _args) in enumerate(reference):
            if tool_name not in EFFECTFUL_TOOLS:
                continue
            for window in CrashWindow:
                cases.append((
                    MatrixCase(
                        case_id=f"{spec.task_id}__{window.value}__step_{step_index}",
                        task_id=spec.task_id,
                        family=spec.family,
                        tier=spec.tier,
                        crash_window=window.value,
                        step_index=step_index,
                        tool_name=tool_name,
                        trajectory_length=len(reference),
                    ),
                    entry,
                ))
    return cases


def run_case(
    case: MatrixCase,
    entry: dict[str, Any],
    case_root: Path,
    *,
    lease_ttl: float,
) -> dict[str, Any]:
    spec = entry["spec"]
    reference = entry["reference"]
    case_root.mkdir(parents=True, exist_ok=True)
    runtime_episode_id = "p4a_" + hashlib.sha256(case.case_id.encode("utf-8")).hexdigest()[:16]

    environment = SupportEnvironment(
        FIXTURE_PATH,
        episode_id=runtime_episode_id,
        workspace=case_root / "episodes",
    ).setup()
    runner_store = RunnerStore(case_root / "runner.sqlite")
    effect_store = EffectStore(environment.connect())
    runner = DeterministicP4Runner(
        runner_store,
        effect_store,
        environment,
        lease_ttl=lease_ttl,
    )

    started = time.perf_counter()
    crash_observed = False
    stale_attempts_before = effect_store.stale_attempts()
    error: str | None = None
    detection_latency_ms = 0.0
    replay_latency_ms = 0.0

    try:
        if case.crash_window is None:
            runner.run(runtime_episode_id, reference, worker_id="worker-a", now=0.0)
        else:
            assert case.step_index is not None
            try:
                runner.run(
                    runtime_episode_id,
                    reference,
                    worker_id="worker-a",
                    now=0.0,
                    crash=CrashInjection(CrashWindow(case.crash_window), case.step_index),
                )
            except P4Crash:
                crash_observed = True
            if not crash_observed:
                raise AssertionError(f"expected injected crash for {case.case_id}")

            # Deterministic latency components, not wall-clock claims.
            detection_latency_ms = lease_ttl * 1000.0
            runner_store.reap_expired(now=lease_ttl + 1.0)
            replay_started = time.perf_counter()
            runner.run(
                runtime_episode_id,
                reference,
                worker_id="worker-b",
                now=lease_ttl + 1.0,
            )
            replay_latency_ms = (time.perf_counter() - replay_started) * 1000.0
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"

    changes = environment.state_diff()
    verification = verify(spec, changes, environment.after_state)
    invariants = verify_invariants(runner_store, effect_store)
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    effectful_steps = [
        index for index, (name, _args) in enumerate(reference) if name in EFFECTFUL_TOOLS
    ]
    duplicate_side_effects = invariants["duplicate_business_mutations"]
    lost_required_effects = 0 if verification.passed else len(verification.missing_required)
    incorrect_final_states = 0 if verification.passed else 1
    stale_fenced_effects_accepted = invariants["stale_fenced_effects_accepted"]
    orphan_effect_records = invariants["effects_without_intent"]
    invariant_violations = sum(invariants.values())

    row = {
        **case.__dict__,
        "crash_observed": crash_observed,
        "runtime_episode_id": runtime_episode_id,
        "expected_effect_records": len(effectful_steps),
        "actual_effect_records": effect_store.effect_count(),
        "intent_records": runner_store.intent_count(),
        "completed_steps": runner_store.completed_count(),
        "runner_state": runner_store.episode(runtime_episode_id)["state"],
        "budget": {
            "consumed_model_turns": runner_store.episode(runtime_episode_id)["consumed_model_turns"],
            "consumed_tokens": runner_store.episode(runtime_episode_id)["consumed_tokens"],
            "consumed_cost": runner_store.episode(runtime_episode_id)["consumed_cost"],
            "tool_call_count": runner_store.episode(runtime_episode_id)["tool_call_count"],
            "retry_count": runner_store.episode(runtime_episode_id)["retry_count"],
        },
        "verification": verification.model_dump(mode="json"),
        "invariants": invariants,
        "acceptance_counts": {
            "duplicate_side_effects": duplicate_side_effects,
            "lost_required_effects": lost_required_effects,
            "incorrect_final_states": incorrect_final_states,
            "stale_fenced_effects_accepted": stale_fenced_effects_accepted,
            "orphan_effect_records": orphan_effect_records,
            "invariant_violations": invariant_violations,
        },
        "stale_token_attempts": effect_store.stale_attempts() - stale_attempts_before,
        "latency": {
            "detection_latency_ms": detection_latency_ms,
            "replay_latency_ms": replay_latency_ms,
            "case_elapsed_ms": elapsed_ms,
        },
        "error": error,
        "passed": (
            error is None
            and verification.passed
            and duplicate_side_effects == 0
            and lost_required_effects == 0
            and incorrect_final_states == 0
            and stale_fenced_effects_accepted == 0
            and orphan_effect_records == 0
            and invariant_violations == 0
            and effect_store.effect_count() == len(effectful_steps)
        ),
    }
    runner_store.close()
    environment.cleanup()
    return row


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    totals = {
        "duplicate_side_effects": 0,
        "lost_required_effects": 0,
        "incorrect_final_states": 0,
        "stale_fenced_effects_accepted": 0,
        "orphan_effect_records": 0,
        "invariant_violations": 0,
    }
    for row in rows:
        for key in totals:
            totals[key] += int(row["acceptance_counts"][key])

    by_window: dict[str, dict[str, int]] = {}
    for row in rows:
        name = row["crash_window"] or "clean"
        bucket = by_window.setdefault(name, {"cases": 0, "passed": 0})
        bucket["cases"] += 1
        bucket["passed"] += int(row["passed"])

    return {
        "cases": len(rows),
        "passed_cases": sum(1 for row in rows if row["passed"]),
        "failed_cases": sum(1 for row in rows if not row["passed"]),
        "crash_cases": sum(1 for row in rows if row["crash_window"] is not None),
        "clean_cases": sum(1 for row in rows if row["crash_window"] is None),
        "acceptance_totals": totals,
        "by_window": dict(sorted(by_window.items())),
    }


def write_quarantine(run_dir: Path, report: dict[str, Any]) -> None:
    failures = [row for row in report["cases"] if not row["passed"]]
    tombstone = {
        "run_id": report["run_id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "contamination_reason": "p4a_protocol_matrix_failure",
        "detection_mechanism": "scripts.run_p4a_matrix acceptance criteria",
        "failed_cases": [
            {
                "case_id": row["case_id"],
                "task_id": row["task_id"],
                "crash_window": row["crash_window"],
                "step_index": row["step_index"],
                "error": row["error"],
                "acceptance_counts": row["acceptance_counts"],
                "verification_passed": row["verification"]["passed"],
            }
            for row in failures
        ],
    }
    (run_dir / "QUARANTINE.json").write_text(
        json.dumps(tombstone, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def run_matrix(
    *,
    run_id: str,
    task_ids: set[str] | None = None,
    output_root: Path = RUN_ROOT,
    lease_ttl: float = 5.0,
    keep_workspace: bool = False,
) -> dict[str, Any]:
    entries = selected_entries(task_ids)
    cases = enumerate_cases(entries)
    run_dir = output_root / run_id
    workspace = run_dir / "workspace"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    workspace.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for index, (case, entry) in enumerate(cases, start=1):
        row = run_case(case, entry, workspace / f"{index:05d}", lease_ttl=lease_ttl)
        rows.append(row)

    report = {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "protocol": "p4a_deterministic_matrix_v1",
        "model_calls_made": 0,
        "versions": {
            "schema": SCHEMA_VERSION,
            "normalization": NORMALIZATION_VERSION,
            "verifier": VERIFIER_VERSION,
            "tools": TOOL_SCHEMA_VERSION,
            "task_families": TASK_FAMILY_VERSION,
        },
        "task_filter": sorted(task_ids) if task_ids else None,
        "lease_ttl_seconds": lease_ttl,
        "summary": aggregate(rows),
        "all_passed": all(row["passed"] for row in rows),
        "cases": rows,
    }
    report_path = run_dir / "p4a_matrix.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if not report["all_passed"]:
        write_quarantine(run_dir, report)

    if not keep_workspace:
        shutil.rmtree(workspace, ignore_errors=True)

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--task-id", action="append", dest="task_ids")
    parser.add_argument("--output-root", type=Path, default=RUN_ROOT)
    parser.add_argument("--lease-ttl", type=float, default=5.0)
    parser.add_argument("--keep-workspace", action="store_true")
    args = parser.parse_args()

    report = run_matrix(
        run_id=args.run_id,
        task_ids=set(args.task_ids) if args.task_ids else None,
        output_root=args.output_root,
        lease_ttl=args.lease_ttl,
        keep_workspace=args.keep_workspace,
    )
    summary = report["summary"]
    print(f"P4a deterministic matrix: {report['run_id']}")
    print(f"  model calls          {report['model_calls_made']}")
    print(f"  cases                {summary['cases']}")
    print(f"  clean/crash          {summary['clean_cases']}/{summary['crash_cases']}")
    print(f"  passed               {summary['passed_cases']}/{summary['cases']}")
    print(f"  acceptance totals    {summary['acceptance_totals']}")
    print(f"  all_passed           {report['all_passed']}")
    print(f"  artifact             {args.output_root / args.run_id / 'p4a_matrix.json'}")
    if not report["all_passed"]:
        print(f"  quarantine           {args.output_root / args.run_id / 'QUARANTINE.json'}")
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
