import pytest
from pydantic import ValidationError

from backend.app.queue_jobs import EvalRunJobPayload
from backend.app.eval_run import EvalRun, RunStatus
from backend.app.queue_jobs import (
    QUEUE_NAME,
    build_run_key,
    enqueue_eval_run,
    load_eval_run,
    save_eval_run,
    update_eval_run_status,
    update_eval_run_trace_id,
)

def test_eval_run_job_payload_accepts_defaults():
    payload = EvalRunJobPayload(run_id="queue_test_001")

    assert payload.job_type == "eval_run"
    assert payload.run_id == "queue_test_001"
    assert payload.dataset_version == "golden_rag_v0.1"
    assert payload.provider_name == "mock"
    assert payload.enqueued_at is not None


def test_eval_run_job_payload_rejects_blank_run_id():
    with pytest.raises(ValidationError):
        EvalRunJobPayload(run_id=" ")

def test_eval_run_job_payload_round_trips_through_json():
    original = EvalRunJobPayload(
        run_id="queue_round_trip_001",
        dataset_version="golden_rag_v0.1",
        provider_name="mock",
    )

    job_json = original.model_dump_json()
    restored = EvalRunJobPayload.model_validate_json(job_json)

    assert restored.job_type == original.job_type
    assert restored.run_id == original.run_id
    assert restored.dataset_version == original.dataset_version
    assert restored.provider_name == original.provider_name


class FakeRedis:
    def __init__(self):
        self.hashes = {}
        self.lists = {}

    def hset(self, key, mapping):
        self.hashes.setdefault(key, {}).update(mapping)

    def hgetall(self, key):
        return self.hashes.get(key, {})

    def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)


def test_save_load_update_and_enqueue_eval_run():
    client = FakeRedis()

    run = EvalRun(
        run_id="run_queue_001",
        dataset_version="golden_rag_v0.1",
        provider_name="mock",
    )
    save_eval_run(client, run)

    stored = load_eval_run(client, "run_queue_001")

    assert stored["run_id"] == "run_queue_001"
    assert stored["status"] == "queued"

    update_eval_run_status(client, "run_queue_001", RunStatus.RUNNING)

    updated = load_eval_run(client, "run_queue_001")
    assert updated["status"] == "running"

    update_eval_run_trace_id(
        client,
        "run_queue_001",
        "0123456789abcdef0123456789abcdef",
    )

    traced = load_eval_run(client, "run_queue_001")
    assert traced["trace_id"] == "0123456789abcdef0123456789abcdef"

    payload = EvalRunJobPayload(run_id="run_queue_001")
    enqueue_eval_run(client, payload)

    assert len(client.lists[QUEUE_NAME]) == 1
    assert build_run_key("run_queue_001") == "eval_run:run_queue_001"
