import sqlite3
from pathlib import Path

import pytest

from backend.app.support.durability import (
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
from backend.app.support.environment import SupportEnvironment
from backend.app.support.schema import DEFAULT_TICKET_COUNT, SCHEMA_VERSION, build_fixture
from backend.app.support.tasks import build_tasks
from backend.app.support.tools import EFFECTFUL_TOOLS, ToolCallIdentity
from backend.app.support.verifier import verify


def _policy_update_case(tmp_path: Path):
    fixture = tmp_path / "support_fixture.sqlite"
    fixture_sha = build_fixture(fixture, DEFAULT_TICKET_COUNT)
    entry = next(
        item for item in build_tasks(fixture, fixture_sha, SCHEMA_VERSION)
        if item["spec"].task_id == "SUP-policy-001"
    )
    environment = SupportEnvironment(fixture, "p4_episode", tmp_path / "episodes").setup()
    effect_store = EffectStore(environment.connect())
    runner_store = RunnerStore(tmp_path / "runner.sqlite")
    runner = DeterministicP4Runner(runner_store, effect_store, environment, lease_ttl=5.0)
    return entry["spec"], entry["reference"], environment, runner_store, effect_store, runner


def _finish_and_verify(spec, environment, runner_store, effect_store):
    changes = environment.state_diff()
    result = verify(spec, changes, environment.after_state)
    assert result.passed, result.model_dump()
    invariants = verify_invariants(runner_store, effect_store)
    assert invariants == {
        "durable_intent_duplicates": 0,
        "effect_result_duplicates": 0,
        "effects_without_intent": 0,
        "completed_without_result": 0,
        "stale_fenced_effects_accepted": 0,
        "duplicate_business_mutations": 0,
    }


def test_p4a_clean_deterministic_reference_reuses_p3_verifier(tmp_path: Path):
    spec, reference, environment, runner_store, effect_store, runner = _policy_update_case(tmp_path)

    runner.run("episode-clean", reference, worker_id="worker-a", now=0.0)

    _finish_and_verify(spec, environment, runner_store, effect_store)
    assert runner_store.intent_count() == len(reference)
    assert runner_store.completed_count() == len(reference)
    assert effect_store.effect_count() == sum(1 for name, _args in reference if name in EFFECTFUL_TOOLS)
    assert runner_store.episode("episode-clean")["state"] == P4State.SUCCEEDED.value


@pytest.mark.parametrize("window", list(CrashWindow))
def test_p4a_crash_matrix_recovers_once_per_effectful_step(tmp_path: Path, window: CrashWindow):
    spec, reference, environment, runner_store, effect_store, runner = _policy_update_case(tmp_path)
    effect_steps = [
        index for index, (name, _args) in enumerate(reference) if name in EFFECTFUL_TOOLS
    ]

    for step_index in effect_steps:
        case_id = f"episode-{window.value}-{step_index}"
        spec, reference, environment, runner_store, effect_store, runner = _policy_update_case(
            tmp_path / f"{window.value}-{step_index}"
        )

        with pytest.raises(P4Crash):
            runner.run(
                case_id,
                reference,
                worker_id="worker-a",
                now=0.0,
                crash=CrashInjection(window, step_index),
            )

        runner_store.reap_expired(now=10.0)
        runner.run(case_id, reference, worker_id="worker-b", now=10.0)

        _finish_and_verify(spec, environment, runner_store, effect_store)
        assert effect_store.effect_count() == len(effect_steps)


def test_p4a_recovery_is_resumable_across_double_crash(tmp_path: Path):
    spec, reference, environment, runner_store, effect_store, runner = _policy_update_case(tmp_path)
    first_effect_step = next(index for index, (name, _args) in enumerate(reference) if name in EFFECTFUL_TOOLS)

    with pytest.raises(P4Crash):
        runner.run(
            "episode-double",
            reference,
            worker_id="worker-a",
            now=0.0,
            crash=CrashInjection(CrashWindow.AFTER_INTENT_BEFORE_EFFECT, first_effect_step),
        )

    runner_store.reap_expired(now=10.0)
    with pytest.raises(P4Crash):
        runner.run(
            "episode-double",
            reference,
            worker_id="worker-b",
            now=10.0,
            crash=CrashInjection(CrashWindow.AFTER_EFFECT_BEFORE_STEP_COMPLETION, first_effect_step),
        )

    runner_store.reap_expired(now=20.0)
    runner.run("episode-double", reference, worker_id="worker-c", now=20.0)

    _finish_and_verify(spec, environment, runner_store, effect_store)
    assert effect_store.effect_count() == sum(1 for name, _args in reference if name in EFFECTFUL_TOOLS)


def test_p4a_zombie_worker_with_stale_fence_cannot_mutate(tmp_path: Path):
    spec, reference, environment, runner_store, effect_store, runner = _policy_update_case(tmp_path)
    episode_id = "episode-zombie"
    runner_store.create_episode(episode_id, len(reference))
    old_token = runner_store.claim_episode(episode_id, "worker-a", now=0.0, ttl=1.0)
    effect_store.install_fence(old_token)

    first_effect_step = next(index for index, (name, _args) in enumerate(reference) if name in EFFECTFUL_TOOLS)
    name, arguments = reference[first_effect_step]
    identity = ToolCallIdentity(episode_id=episode_id, step_index=first_effect_step, call_index=0)
    runner_store.record_model_decision(episode_id)
    intent = runner_store.write_intent(identity, name, arguments)

    runner_store.reap_expired(now=2.0)
    runner.run(episode_id, reference, worker_id="worker-b", now=2.0)

    with pytest.raises(StaleFenceError):
        effect_store.invoke_effect(intent, old_token)

    _finish_and_verify(spec, environment, runner_store, effect_store)
    assert effect_store.stale_attempts() > 0
    assert effect_store.stale_accepted() == 0
    assert effect_store.duplicate_business_mutations() == 0


def test_p4a_intent_identity_is_immutable(tmp_path: Path):
    _spec, _reference, _environment, runner_store, _effect_store, _runner = _policy_update_case(tmp_path)
    runner_store.create_episode("episode-intent", 1)
    identity = ToolCallIdentity(episode_id="episode-intent", step_index=0, call_index=0)

    runner_store.write_intent(identity, "update_ticket", {"ticket_id": "TKT-0001", "priority": "high"})

    with pytest.raises(ProtocolViolation):
        runner_store.write_intent(
            identity,
            "update_ticket",
            {"ticket_id": "TKT-0001", "priority": "urgent"},
        )


def test_p4a_idempotency_conflict_fails_closed(tmp_path: Path):
    _spec, _reference, _environment, _runner_store, effect_store, _runner = _policy_update_case(tmp_path)
    identity = ToolCallIdentity(episode_id="episode-effect", step_index=0, call_index=0)
    good = RunnerStore(tmp_path / "runner-good.sqlite")
    good.create_episode("episode-effect", 1)
    token = good.claim_episode("episode-effect", "worker-a", now=0.0, ttl=5.0)
    effect_store.install_fence(token)
    intent = good.write_intent(
        identity,
        "update_ticket",
        {"ticket_id": "TKT-0001", "priority": "high"},
    )
    effect_store.invoke_effect(intent, token)

    bad = RunnerStore(tmp_path / "runner-bad.sqlite")
    bad.create_episode("episode-effect", 1)
    conflicting = bad.write_intent(
        identity,
        "update_ticket",
        {"ticket_id": "TKT-0001", "priority": "urgent"},
    )
    with pytest.raises(ProtocolViolation):
        effect_store.invoke_effect(conflicting, token)


def test_p4a_poisoned_episode_reaches_dlq_without_effects(tmp_path: Path):
    _spec, _reference, _environment, runner_store, effect_store, _runner = _policy_update_case(tmp_path)
    runner_store.create_episode("episode-poison", 1)
    token = runner_store.claim_episode("episode-poison", "worker-a", now=0.0, ttl=1.0)
    effect_store.install_fence(token)
    identity = ToolCallIdentity(episode_id="episode-poison", step_index=0, call_index=0)
    intent = runner_store.write_intent(
        identity,
        "assign_ticket",
        {"ticket_id": "TKT-0001", "team_id": "TEAM-does-not-exist"},
    )

    for attempt in range(3):
        with pytest.raises(ProtocolViolation):
            effect_store.invoke_effect(intent, token)
        runner_store.record_failure("episode-poison", "no such team", max_retries=3)
        if attempt < 2:
            runner_store.claim_episode("episode-poison", f"worker-{attempt}", now=attempt + 1.0, ttl=1.0)

    episode = runner_store.episode("episode-poison")
    assert episode["state"] == P4State.DLQ.value
    assert episode["retry_count"] == 3
    assert effect_store.effect_count() == 0
