"""Run P4a supplemental recovery/failure scenarios outside the 915-case matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
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
    P4State,
    ProtocolViolation,
    RunnerStore,
    StaleFenceError,
    verify_invariants,
)
from backend.app.support.environment import SupportEnvironment  # noqa: E402
from backend.app.support.schema import SCHEMA_VERSION  # noqa: E402
from backend.app.support.tasks import build_tasks  # noqa: E402
from backend.app.support.tools import EFFECTFUL_TOOLS, ToolCallIdentity  # noqa: E402
from backend.app.support.verifier import verify  # noqa: E402


FIXTURE_PATH = REPO_ROOT / "datasets" / "support" / "support_fixture.sqlite"
MANIFEST_PATH = REPO_ROOT / "config" / "p3_frozen_manifest.json"
RUN_ROOT = REPO_ROOT / "runs" / "p4a_supplemental"


def _entry() -> dict[str, Any]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return next(
        item
        for item in build_tasks(FIXTURE_PATH, manifest["fixture_sha256"], SCHEMA_VERSION)
        if item["spec"].task_id == "SUP-policy-001"
    )


def _case_runtime(case_name: str, case_root: Path) -> tuple[
    dict[str, Any],
    SupportEnvironment,
    RunnerStore,
    EffectStore,
    DeterministicP4Runner,
    str,
]:
    entry = _entry()
    runtime_episode_id = "p4a_" + hashlib.sha256(case_name.encode("utf-8")).hexdigest()[:16]
    environment = SupportEnvironment(
        FIXTURE_PATH,
        episode_id=runtime_episode_id,
        workspace=case_root / "episodes",
    ).setup()
    runner_store = RunnerStore(case_root / "runner.sqlite")
    effect_store = EffectStore(environment.connect())
    runner = DeterministicP4Runner(runner_store, effect_store, environment, lease_ttl=5.0)
    return entry, environment, runner_store, effect_store, runner, runtime_episode_id


def _final_state_row(
    *,
    case_name: str,
    episode_id: str,
    spec: Any,
    environment: SupportEnvironment,
    runner_store: RunnerStore,
    effect_store: EffectStore,
    expect_verifier_pass: bool,
    extra: dict[str, Any],
) -> dict[str, Any]:
    verification = None
    if expect_verifier_pass:
        changes = environment.state_diff()
        verification = verify(spec, changes, environment.after_state).model_dump(mode="json")
    invariants = verify_invariants(runner_store, effect_store)
    episode = runner_store.episode(episode_id)
    row = {
        "case_name": case_name,
        "runtime_episode_id": episode_id,
        "runner_state": episode["state"],
        "retry_count": episode["retry_count"],
        "intent_records": runner_store.intent_count(),
        "completed_steps": runner_store.completed_count(),
        "effect_records": effect_store.effect_count(),
        "stale_token_attempts": effect_store.stale_attempts(),
        "stale_fenced_effects_accepted": effect_store.stale_accepted(),
        "duplicate_business_mutations": effect_store.duplicate_business_mutations(),
        "invariants": invariants,
        "verification": verification,
        **extra,
    }
    return row


def _close(environment: SupportEnvironment, runner_store: RunnerStore) -> None:
    runner_store.close()
    environment.cleanup()


def double_crash(case_root: Path) -> dict[str, Any]:
    entry, environment, runner_store, effect_store, runner, episode_id = _case_runtime(
        "double_crash_recovery", case_root
    )
    spec = entry["spec"]
    reference = entry["reference"]
    first_effect_step = next(index for index, (name, _args) in enumerate(reference) if name in EFFECTFUL_TOOLS)
    crashes_observed = 0
    try:
        try:
            runner.run(
                episode_id,
                reference,
                worker_id="worker-a",
                now=0.0,
                crash=CrashInjection(CrashWindow.AFTER_INTENT_BEFORE_EFFECT, first_effect_step),
            )
        except P4Crash:
            crashes_observed += 1
        runner_store.reap_expired(now=10.0)
        try:
            runner.run(
                episode_id,
                reference,
                worker_id="worker-b",
                now=10.0,
                crash=CrashInjection(CrashWindow.AFTER_EFFECT_BEFORE_STEP_COMPLETION, first_effect_step),
            )
        except P4Crash:
            crashes_observed += 1
        runner_store.reap_expired(now=20.0)
        runner.run(episode_id, reference, worker_id="worker-c", now=20.0)
        row = _final_state_row(
            case_name="double_crash_recovery",
            episode_id=episode_id,
            spec=spec,
            environment=environment,
            runner_store=runner_store,
            effect_store=effect_store,
            expect_verifier_pass=True,
            extra={
                "crashes_observed": crashes_observed,
                "expected_crashes": 2,
                "passed": crashes_observed == 2,
            },
        )
        row["passed"] = row["passed"] and row["verification"]["passed"] and all(
            value == 0 for value in row["invariants"].values()
        )
        return row
    finally:
        _close(environment, runner_store)


def stale_worker_fencing(case_root: Path) -> dict[str, Any]:
    entry, environment, runner_store, effect_store, runner, episode_id = _case_runtime(
        "stale_worker_fencing", case_root
    )
    spec = entry["spec"]
    reference = entry["reference"]
    first_effect_step = next(index for index, (name, _args) in enumerate(reference) if name in EFFECTFUL_TOOLS)
    name, arguments = reference[first_effect_step]
    stale_rejected = False
    try:
        runner_store.create_episode(episode_id, len(reference))
        old_token = runner_store.claim_episode(episode_id, "worker-a", now=0.0, ttl=1.0)
        effect_store.install_fence(old_token)
        identity = ToolCallIdentity(episode_id=episode_id, step_index=first_effect_step, call_index=0)
        runner_store.record_model_decision(episode_id)
        intent = runner_store.write_intent(identity, name, arguments)

        runner_store.reap_expired(now=2.0)
        runner.run(episode_id, reference, worker_id="worker-b", now=2.0)
        try:
            effect_store.invoke_effect(intent, old_token)
        except StaleFenceError:
            stale_rejected = True

        row = _final_state_row(
            case_name="stale_worker_fencing",
            episode_id=episode_id,
            spec=spec,
            environment=environment,
            runner_store=runner_store,
            effect_store=effect_store,
            expect_verifier_pass=True,
            extra={
                "stale_rejected": stale_rejected,
                "passed": stale_rejected,
            },
        )
        row["passed"] = (
            row["passed"]
            and row["verification"]["passed"]
            and row["stale_token_attempts"] > 0
            and row["stale_fenced_effects_accepted"] == 0
            and row["duplicate_business_mutations"] == 0
        )
        return row
    finally:
        _close(environment, runner_store)


def poison_dlq(case_root: Path) -> dict[str, Any]:
    entry, environment, runner_store, effect_store, _runner, episode_id = _case_runtime(
        "poison_dlq", case_root
    )
    protocol_violations = 0
    try:
        runner_store.create_episode(episode_id, 1)
        token = runner_store.claim_episode(episode_id, "worker-a", now=0.0, ttl=1.0)
        effect_store.install_fence(token)
        identity = ToolCallIdentity(episode_id=episode_id, step_index=0, call_index=0)
        intent = runner_store.write_intent(
            identity,
            "assign_ticket",
            {"ticket_id": "TKT-0001", "team_id": "TEAM-does-not-exist"},
        )
        for attempt in range(3):
            try:
                effect_store.invoke_effect(intent, token)
            except ProtocolViolation:
                protocol_violations += 1
            runner_store.record_failure(episode_id, "no such team", max_retries=3)
            if attempt < 2:
                token = runner_store.claim_episode(
                    episode_id, f"worker-retry-{attempt}", now=attempt + 1.0, ttl=1.0
                )
                effect_store.install_fence(token)

        row = _final_state_row(
            case_name="poison_dlq",
            episode_id=episode_id,
            spec=entry["spec"],
            environment=environment,
            runner_store=runner_store,
            effect_store=effect_store,
            expect_verifier_pass=False,
            extra={
                "protocol_violations": protocol_violations,
                "expected_protocol_violations": 3,
                "passed": True,
            },
        )
        row["passed"] = (
            row["runner_state"] == P4State.DLQ.value
            and row["retry_count"] == 3
            and row["effect_records"] == 0
            and protocol_violations == 3
        )
        return row
    finally:
        _close(environment, runner_store)


def run_supplemental(
    *,
    run_id: str,
    output_root: Path = RUN_ROOT,
    keep_workspace: bool = False,
) -> dict[str, Any]:
    run_dir = output_root / run_id
    workspace = run_dir / "workspace"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    workspace.mkdir(parents=True, exist_ok=True)

    cases = [
        double_crash(workspace / "double_crash"),
        stale_worker_fencing(workspace / "stale_worker_fencing"),
        poison_dlq(workspace / "poison_dlq"),
    ]
    report = {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "protocol": "p4a_supplemental_recovery_v1",
        "model_calls_made": 0,
        "cases": cases,
        "summary": {
            "cases": len(cases),
            "passed_cases": sum(1 for case in cases if case["passed"]),
            "failed_cases": sum(1 for case in cases if not case["passed"]),
            "double_crash_recovery_cases": sum(1 for case in cases if case["case_name"] == "double_crash_recovery"),
            "stale_worker_fencing_cases": sum(1 for case in cases if case["case_name"] == "stale_worker_fencing"),
            "poison_dlq_cases": sum(1 for case in cases if case["case_name"] == "poison_dlq"),
        },
        "all_passed": all(case["passed"] for case in cases),
    }
    report_path = run_dir / "p4a_supplemental.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not keep_workspace:
        shutil.rmtree(workspace, ignore_errors=True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path, default=RUN_ROOT)
    parser.add_argument("--keep-workspace", action="store_true")
    args = parser.parse_args()
    report = run_supplemental(
        run_id=args.run_id,
        output_root=args.output_root,
        keep_workspace=args.keep_workspace,
    )
    print(f"P4a supplemental recovery: {report['run_id']}")
    print(f"  model calls {report['model_calls_made']}")
    print(f"  passed      {report['summary']['passed_cases']}/{report['summary']['cases']}")
    print(f"  all_passed  {report['all_passed']}")
    print(f"  artifact    {args.output_root / args.run_id / 'p4a_supplemental.json'}")
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
