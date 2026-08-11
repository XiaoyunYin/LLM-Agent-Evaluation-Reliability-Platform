from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from backend.app.eval_run import EvalRun, RunStatus


class EvalRunJobPayload(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    job_type: Literal["eval_run"] = "eval_run"
    run_id: str
    dataset_version: str = "golden_rag_v0.1"
    provider_name: str = "mock"
    model_name: str | None = None
    task_family: str = "rag"
    retrieval_mode: str = "hybrid_rrf_k60_top10_context4"
    prompt_version: str = "rag_prompt_v1"
    repeat_id: str = "repeat_01"
    matrix_id: str = "manual"
    expected_case_count: int | None = None
    enqueued_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator(
        "run_id",
        "dataset_version",
        "provider_name",
        "task_family",
        "retrieval_mode",
        "prompt_version",
        "repeat_id",
        "matrix_id",
    )
    @classmethod
    def required_strings_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("model_name")
    @classmethod
    def optional_model_name_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be empty")
        return value

QUEUE_NAME = "eval_run_jobs"
RUN_KEY_PREFIX = "eval_run"


def build_run_key(run_id: str) -> str:
    return f"{RUN_KEY_PREFIX}:{run_id}"


def save_eval_run(client, run: EvalRun) -> None:
    client.hset(
        build_run_key(run.run_id),
        mapping={
            "run_id": run.run_id,
            "dataset_version": run.dataset_version,
            "provider_name": run.provider_name,
            "status": run.status.value,
            "started_at": run.started_at.isoformat(),
        },
    )


def save_eval_run_metadata(client, run_id: str, metadata: dict) -> None:
    clean_metadata = {
        key: value
        for key, value in metadata.items()
        if value is not None
    }
    if not clean_metadata:
        return
    client.hset(build_run_key(run_id), mapping=clean_metadata)


def load_eval_run(client, run_id: str) -> dict | None:
    data = client.hgetall(build_run_key(run_id))

    if not data:
        return None

    return data


def update_eval_run_status(client, run_id: str, status: RunStatus) -> None:
    client.hset(
        build_run_key(run_id),
        mapping={
            "status": status.value,
        },
    )


def update_eval_run_trace_id(client, run_id: str, trace_id: str) -> None:
    client.hset(
        build_run_key(run_id),
        mapping={
            "trace_id": trace_id,
        },
    )


def enqueue_eval_run(client, payload: EvalRunJobPayload) -> None:
    client.rpush(QUEUE_NAME, payload.model_dump_json())
