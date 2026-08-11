import os
import sys
import argparse
from pathlib import Path

import redis
from dotenv import load_dotenv
from pydantic import ValidationError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from backend.app.candidate_generation import (
    CandidateGenerationRunConfig,
    generate_candidate_answers_for_run,
)
from backend.app.eval_run import RunStatus
from backend.app.tracing import (
    SERVICE_LAYER_GATEWAY,
    SERVICE_LAYER_JUDGE,
    SERVICE_LAYER_PROVIDER,
    SERVICE_LAYER_RETRIEVAL,
    SERVICE_LAYER_STORAGE,
    SERVICE_LAYER_TOOL,
    current_trace_id,
    get_tracer,
    set_common_span_attributes,
)
from backend.app.queue_jobs import (
    QUEUE_NAME,
    load_eval_run,
    update_eval_run_status,
    update_eval_run_trace_id,
)
from backend.app.queue_jobs import EvalRunJobPayload


DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/0"



def handle_eval_run_job(payload: EvalRunJobPayload, client: redis.Redis) -> None:
    tracer = get_tracer()

    with tracer.start_as_current_span("eval_runner.handle_eval_run") as span:
        span.set_attribute("eval.run_id", payload.run_id)
        span.set_attribute("eval.dataset_version", payload.dataset_version)
        span.set_attribute("eval.provider_name", payload.provider_name)

        trace_id = current_trace_id()

        record_gateway_span(
            payload=payload,
            trace_id=trace_id,
        )

        stored_run = load_eval_run_with_span(
            client=client,
            run_id=payload.run_id,
        )

        if stored_run is None:
            span.set_attribute("eval.job_status", "skipped_missing_run")
            print(f"missing run_id={payload.run_id}; marking job skipped")
            return

        update_eval_run_status_with_span(
            client=client,
            run_id=payload.run_id,
            status=RunStatus.RUNNING,
        )
        update_eval_run_trace_id_with_span(
            client=client,
            run_id=payload.run_id,
            trace_id=trace_id or "",
        )

        try:
            record_retrieval_span(
                payload=payload,
                trace_id=trace_id,
            )
            record_provider_span(
                payload=payload,
                trace_id=trace_id,
            )
            record_judge_span(
                payload=payload,
                trace_id=trace_id,
            )
            record_tool_span(
                payload=payload,
                trace_id=trace_id,
            )

            result_key = f"eval_run_result:{payload.run_id}"

            if should_generate_candidate_answers(payload):
                generation_summary = generate_candidate_answers_for_run(
                    CandidateGenerationRunConfig(
                        run_id=payload.run_id,
                        dataset_version=payload.dataset_version,
                        provider_name=payload.provider_name,
                        model_name=payload.model_name or payload.provider_name,
                        task_family=payload.task_family,
                        retrieval_mode=payload.retrieval_mode,
                        prompt_version=payload.prompt_version,
                        repeat_id=payload.repeat_id,
                        matrix_id=payload.matrix_id,
                        expected_case_count=payload.expected_case_count,
                    )
                )
                result = {
                    "run_id": payload.run_id,
                    "trace_id": trace_id or "",
                    "status": generation_summary.status,
                    "message": "Candidate generation completed.",
                    "provider_name": payload.provider_name,
                    "model_name": payload.model_name or "",
                    "dataset_version": payload.dataset_version,
                    "candidate_answer_count": generation_summary.final_completed_count,
                    "output_path": generation_summary.output_path,
                }
                if generation_summary.status != "completed":
                    raise RuntimeError(
                        "Candidate generation did not complete: "
                        f"{generation_summary.model_dump(mode='json')}"
                    )
            else:
                # Tiny placeholder for local queue and tracing smoke tests.
                result = {
                    "run_id": payload.run_id,
                    "trace_id": trace_id or "",
                    "status": "completed",
                    "message": "Tiny worker test completed.",
                    "provider_name": payload.provider_name,
                    "dataset_version": payload.dataset_version,
                }

            store_eval_run_result_with_span(
                client=client,
                result_key=result_key,
                result=result,
            )
            update_eval_run_status_with_span(
                client=client,
                run_id=payload.run_id,
                status=RunStatus.COMPLETED,
            )
            span.set_attribute("eval.job_status", "completed")

            print(f"processed run_id={payload.run_id}")
            print(f"trace_id={trace_id}")
            print(f"stored result_key={result_key}")

        except Exception as error:
            span.record_exception(error)
            span.set_attribute("eval.job_status", "failed")
            update_eval_run_status_with_span(
                client=client,
                run_id=payload.run_id,
                status=RunStatus.FAILED,
            )
            print(f"failed run_id={payload.run_id}")
            print(f"trace_id={trace_id}")
            print(error)


def should_generate_candidate_answers(payload: EvalRunJobPayload) -> bool:
    return payload.provider_name in {"openai", "anthropic"} and payload.model_name is not None


def record_gateway_span(
    payload: EvalRunJobPayload,
    trace_id: str | None,
) -> None:
    tracer = get_tracer()

    with tracer.start_as_current_span("gateway.accept_eval_run_job") as span:
        set_common_span_attributes(
            span=span,
            layer=SERVICE_LAYER_GATEWAY,
            run_id=payload.run_id,
            trace_id=trace_id,
        )
        span.set_attribute("messaging.system", "redis")
        span.set_attribute("messaging.destination", QUEUE_NAME)
        span.set_attribute("eval.job_type", payload.job_type)
        span.set_attribute("eval.dataset_version", payload.dataset_version)
        span.set_attribute("eval.provider_name", payload.provider_name)
        span.set_attribute("eval.layer_status", "completed")


def record_retrieval_span(
    payload: EvalRunJobPayload,
    trace_id: str | None,
) -> None:
    tracer = get_tracer()

    with tracer.start_as_current_span("retrieval.fetch_context") as span:
        set_common_span_attributes(
            span=span,
            layer=SERVICE_LAYER_RETRIEVAL,
            run_id=payload.run_id,
            trace_id=trace_id,
        )
        span.set_attribute("retrieval.strategy", "hybrid_rrf")
        span.set_attribute("retrieval.dense_top_k", 50)
        span.set_attribute("retrieval.bm25_top_k", 50)
        span.set_attribute("retrieval.rrf_k", 60)
        span.set_attribute("retrieval.final_top_k", 10)
        span.set_attribute("eval.layer_status", "placeholder")


def record_provider_span(
    payload: EvalRunJobPayload,
    trace_id: str | None,
) -> None:
    tracer = get_tracer()

    with tracer.start_as_current_span("provider.generate_candidate_answer") as span:
        set_common_span_attributes(
            span=span,
            layer=SERVICE_LAYER_PROVIDER,
            run_id=payload.run_id,
            trace_id=trace_id,
        )
        span.set_attribute("llm.provider", payload.provider_name)
        span.set_attribute("llm.candidate_count", 0)
        span.set_attribute("eval.dataset_version", payload.dataset_version)
        span.set_attribute("eval.layer_status", "placeholder")


def record_judge_span(
    payload: EvalRunJobPayload,
    trace_id: str | None,
) -> None:
    tracer = get_tracer()

    with tracer.start_as_current_span("judge.score_candidate_answer") as span:
        set_common_span_attributes(
            span=span,
            layer=SERVICE_LAYER_JUDGE,
            run_id=payload.run_id,
            trace_id=trace_id,
        )
        span.set_attribute("judge.primary", "self_hosted_7b")
        span.set_attribute("judge.validation", "gpt4o_mini_slice")
        span.set_attribute("judge.score_count", 0)
        span.set_attribute("eval.layer_status", "placeholder")


def record_tool_span(
    payload: EvalRunJobPayload,
    trace_id: str | None,
) -> None:
    tracer = get_tracer()

    with tracer.start_as_current_span("tool.execute_agent_tool") as span:
        set_common_span_attributes(
            span=span,
            layer=SERVICE_LAYER_TOOL,
            run_id=payload.run_id,
            trace_id=trace_id,
        )
        span.set_attribute("tool.enabled", True)
        span.set_attribute("tool.call_count", 0)
        span.set_attribute("eval.layer_status", "placeholder")


def load_eval_run_with_span(client: redis.Redis, run_id: str) -> dict | None:
    tracer = get_tracer()

    with tracer.start_as_current_span("eval_runner.load_eval_run") as span:
        set_common_span_attributes(
            span=span,
            layer=SERVICE_LAYER_STORAGE,
            run_id=run_id,
            trace_id=current_trace_id(),
        )
        span.set_attribute("eval.run_id", run_id)
        stored_run = load_eval_run(client, run_id)
        span.set_attribute("eval.run_found", stored_run is not None)
        return stored_run


def update_eval_run_status_with_span(
    client: redis.Redis,
    run_id: str,
    status: RunStatus,
) -> None:
    tracer = get_tracer()

    with tracer.start_as_current_span("eval_runner.update_eval_run_status") as span:
        set_common_span_attributes(
            span=span,
            layer=SERVICE_LAYER_STORAGE,
            run_id=run_id,
            trace_id=current_trace_id(),
        )
        span.set_attribute("eval.status", status.value)
        update_eval_run_status(client, run_id, status)


def update_eval_run_trace_id_with_span(
    client: redis.Redis,
    run_id: str,
    trace_id: str,
) -> None:
    tracer = get_tracer()

    with tracer.start_as_current_span("eval_runner.connect_trace_to_run") as span:
        set_common_span_attributes(
            span=span,
            layer=SERVICE_LAYER_STORAGE,
            run_id=run_id,
            trace_id=trace_id,
        )
        update_eval_run_trace_id(client, run_id, trace_id)


def store_eval_run_result_with_span(
    client: redis.Redis,
    result_key: str,
    result: dict,
) -> None:
    tracer = get_tracer()

    with tracer.start_as_current_span("eval_runner.store_eval_run_result") as span:
        set_common_span_attributes(
            span=span,
            layer=SERVICE_LAYER_STORAGE,
            run_id=result["run_id"],
            trace_id=result.get("trace_id", ""),
        )
        span.set_attribute("eval.result_key", result_key)
        span.set_attribute("eval.layer_status", "completed")
        client.hset(result_key, mapping=result)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-jobs", type=int, default=None)
    parser.add_argument("--idle-timeout-seconds", type=int, default=0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    redis_url = os.getenv("REDIS_URL", DEFAULT_REDIS_URL)
    client = redis.Redis.from_url(redis_url, decode_responses=True)

    print(f"worker listening queue={QUEUE_NAME}")
    processed = 0

    while True:
        item = client.blpop(
            QUEUE_NAME,
            timeout=args.idle_timeout_seconds if args.idle_timeout_seconds > 0 else 0,
        )
        if item is None:
            print("worker idle timeout reached")
            return

        _, job_json = item

        try:
            payload = EvalRunJobPayload.model_validate_json(job_json)
        except ValidationError as error:
            print("invalid job payload")
            print(error)
            continue

        handle_eval_run_job(payload, client)
        processed += 1

        if args.max_jobs is not None and processed >= args.max_jobs:
            print(f"worker processed max_jobs={args.max_jobs}")
            return


if __name__ == "__main__":
    main()
