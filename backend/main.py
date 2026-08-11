from fastapi import FastAPI, HTTPException
import os
from datetime import datetime, timezone
from pathlib import Path

import redis
from pydantic import BaseModel, ConfigDict
from backend.app.dashboard_metrics import (
    MetricsSummaryResponse,
    build_metrics_summary,
    load_review_cases_from_artifacts,
)
from backend.app.eval_run import EvalRun
from backend.app.tracing import current_trace_id, get_tracer
from backend.app.queue_jobs import (
    EvalRunJobPayload,
    enqueue_eval_run,
    load_eval_run,
    save_eval_run,
    save_eval_run_metadata,
)

app = FastAPI(title="LLM Eval Regression Platform")

DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/0"


def get_redis_client():
    redis_url = os.getenv("REDIS_URL", DEFAULT_REDIS_URL)
    return redis.Redis.from_url(redis_url, decode_responses=True)

class CreateRunRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    run_id: str | None = None
    dataset_version: str = "golden_rag_v0.1"
    provider_name: str = "mock"
    model_name: str | None = None
    task_family: str = "rag"
    retrieval_mode: str = "hybrid_rrf_k60_top10_context4"
    prompt_version: str = "rag_prompt_v1"
    repeat_id: str = "repeat_01"
    matrix_id: str = "manual"
    expected_case_count: int | None = None


class RunResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    run_id: str
    dataset_version: str
    provider_name: str
    status: str
    started_at: str | None = None
    model_name: str | None = None
    task_family: str | None = None
    retrieval_mode: str | None = None
    prompt_version: str | None = None
    repeat_id: str | None = None
    matrix_id: str | None = None


class EvalRunSummaryResponse(BaseModel):
    run_id: str
    dataset_version: str
    provider_name: str
    status: str
    created_at: str | None = None
    score: float | None = None
    latency_ms: float | None = None
    total_cases: int | None = None
    passed_cases: int | None = None


class ReviewCaseResponse(BaseModel):
    id: str
    run_id: str
    case_id: str
    disagreement_reason: str
    answer: str
    judge_a_score: float
    judge_b_score: float
    human_label: str | None = None
    final_decision: str | None = None
    status: str


class ReviewDecisionUpdate(BaseModel):
    human_label: str
    final_decision: str

class ReviewStatusUpdate(BaseModel):
    status: str

def create_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"eval_run_{timestamp}"

EVAL_RUNS = {
    "local_mock_001": {
        "run_id": "local_mock_001",
        "dataset_version": "golden_rag_v0.1",
        "provider_name": "mock",
        "status": "completed",
        "created_at": "2026-07-30T05:47:34+00:00",
        "score": None,
        "latency_ms": None,
        "total_cases": 3,
        "passed_cases": 2,
    }
}

REVIEW_CASES = {
    "review_case_001": {
        "id": "review_case_001",
        "run_id": "local_mock_001",
        "case_id": "rag_case_001",
        "disagreement_reason": "judge_scores_disagree",
        "answer": "The customer can reset their API key from account settings.",
        "judge_a_score": 0.9,
        "judge_b_score": 0.4,
        "human_label": None,
        "final_decision": None,
        "status": "pending",
    }
}


def ensure_review_case_loaded(review_case_id: str) -> None:
    if review_case_id in REVIEW_CASES:
        return

    for artifact_case in load_review_cases_from_artifacts(Path("runs")):
        if artifact_case["id"] == review_case_id:
            REVIEW_CASES[review_case_id] = artifact_case
            return


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}

@app.get("/eval-runs", response_model=list[EvalRunSummaryResponse])
def list_eval_runs() -> list[EvalRunSummaryResponse]:
    return [
        EvalRunSummaryResponse(**run)
        for run in EVAL_RUNS.values()
    ]

@app.get("/eval-runs/{run_id}")
def get_eval_run(run_id: str) -> dict:
    if run_id not in EVAL_RUNS:
        raise HTTPException(status_code=404, detail="Eval run not found")

    return EVAL_RUNS[run_id]

@app.get("/metrics-summary", response_model=MetricsSummaryResponse)
def get_metrics_summary() -> MetricsSummaryResponse:
    return build_metrics_summary()


@app.get("/review-cases", response_model=list[ReviewCaseResponse])
def list_review_cases() -> list[ReviewCaseResponse]:
    cases_by_id = {
        case["id"]: ReviewCaseResponse(**case)
        for case in REVIEW_CASES.values()
    }

    for artifact_case in load_review_cases_from_artifacts(Path("runs")):
        case = ReviewCaseResponse(**artifact_case)
        cases_by_id.setdefault(case.id, case)

    return list(cases_by_id.values())

@app.get("/review-cases/{review_case_id}")
def get_review_case(review_case_id: str) -> dict:
    ensure_review_case_loaded(review_case_id)
    if review_case_id not in REVIEW_CASES:
        raise HTTPException(status_code=404, detail="Review case not found")

    return REVIEW_CASES[review_case_id]

@app.patch("/review-cases/{review_case_id}/decision")
def update_review_case_decision(
    review_case_id: str,
    request: ReviewDecisionUpdate,
) -> dict:
    ensure_review_case_loaded(review_case_id)
    if review_case_id not in REVIEW_CASES:
        raise HTTPException(status_code=404, detail="Review case not found")

    REVIEW_CASES[review_case_id]["human_label"] = request.human_label
    REVIEW_CASES[review_case_id]["final_decision"] = request.final_decision

    return REVIEW_CASES[review_case_id]

@app.patch("/review-cases/{review_case_id}/status")
def update_review_case_status(
    review_case_id: str,
    request: ReviewStatusUpdate,
) -> dict:
    ensure_review_case_loaded(review_case_id)
    if review_case_id not in REVIEW_CASES:
        raise HTTPException(status_code=404, detail="Review case not found")

    if request.status not in {"pending", "reviewed", "resolved"}:
        raise HTTPException(status_code=400, detail="Invalid review status")

    REVIEW_CASES[review_case_id]["status"] = request.status

    return REVIEW_CASES[review_case_id]

@app.post("/runs", response_model=RunResponse)
def create_run(request: CreateRunRequest) -> RunResponse:
    tracer = get_tracer()

    with tracer.start_as_current_span("api.create_eval_run") as span:
        client = get_redis_client()
        run_id = request.run_id or create_run_id()
        span.set_attribute("eval.run_id", run_id)
        span.set_attribute("eval.dataset_version", request.dataset_version)
        span.set_attribute("eval.provider_name", request.provider_name)

        run = EvalRun(
            run_id=run_id,
            dataset_version=request.dataset_version,
            provider_name=request.provider_name,
        )

        payload = EvalRunJobPayload(
            run_id=run.run_id,
            dataset_version=run.dataset_version,
            provider_name=run.provider_name,
            model_name=request.model_name,
            task_family=request.task_family,
            retrieval_mode=request.retrieval_mode,
            prompt_version=request.prompt_version,
            repeat_id=request.repeat_id,
            matrix_id=request.matrix_id,
            expected_case_count=request.expected_case_count,
        )

        save_eval_run(client, run)
        save_eval_run_metadata(
            client,
            run_id=run.run_id,
            metadata={
                "model_name": request.model_name or "",
                "task_family": request.task_family,
                "retrieval_mode": request.retrieval_mode,
                "prompt_version": request.prompt_version,
                "repeat_id": request.repeat_id,
                "matrix_id": request.matrix_id,
                "expected_case_count": request.expected_case_count,
            },
        )
        enqueue_eval_run(client, payload)
        span.set_attribute("trace.id", current_trace_id() or "")

        return RunResponse(
            run_id=run.run_id,
            dataset_version=run.dataset_version,
            provider_name=run.provider_name,
            status=run.status.value,
            started_at=run.started_at.isoformat(),
            model_name=request.model_name,
            task_family=request.task_family,
            retrieval_mode=request.retrieval_mode,
            prompt_version=request.prompt_version,
            repeat_id=request.repeat_id,
            matrix_id=request.matrix_id,
        )


@app.get("/runs/{run_id}", response_model=RunResponse)
def get_run(run_id: str) -> RunResponse:
    tracer = get_tracer()

    with tracer.start_as_current_span("api.get_eval_run") as span:
        span.set_attribute("eval.run_id", run_id)
        client = get_redis_client()
        stored_run = load_eval_run(client, run_id)
        span.set_attribute("eval.run_found", stored_run is not None)

        if stored_run is None:
            raise HTTPException(status_code=404, detail="Eval run not found")

        return RunResponse(
            run_id=stored_run["run_id"],
            dataset_version=stored_run["dataset_version"],
            provider_name=stored_run["provider_name"],
            status=stored_run["status"],
            started_at=stored_run.get("started_at"),
            model_name=stored_run.get("model_name") or None,
            task_family=stored_run.get("task_family"),
            retrieval_mode=stored_run.get("retrieval_mode"),
            prompt_version=stored_run.get("prompt_version"),
            repeat_id=stored_run.get("repeat_id"),
            matrix_id=stored_run.get("matrix_id"),
        )
