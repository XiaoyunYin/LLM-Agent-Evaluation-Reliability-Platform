import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from backend.app.bm25_retrieval import ElasticsearchBm25Retriever
from backend.app.dataset_loader import load_eval_cases
from backend.app.dense_retrieval import PostgresDenseRetriever
from backend.app.embeddings import OpenAIEmbeddingProvider
from backend.app.eval_case import EvalCase, TaskType
from backend.app.eval_run import CandidateAnswer
from backend.app.generation import (
    build_rag_generation_request,
    generate_answer,
    retrieve_context_and_build_rag_request,
)
from backend.app.hybrid_retrieval import HybridRetriever, RRF_K
from backend.app.tracing import (
    SERVICE_LAYER_PROVIDER,
    SERVICE_LAYER_RETRIEVAL,
    SERVICE_LAYER_STORAGE,
    current_trace_id,
    get_tracer,
    set_common_span_attributes,
)
from backend.app.providers import (
    SelfHostedProvider,
    AnthropicProvider,
    GenerationRequest,
    GenerationResponse,
    LLMProvider,
    OpenAIProvider,
)


DEFAULT_OUTPUT_DIR = Path("runs/candidate_generation")

DATASET_PATHS = {
    # v0.1 is retained because versioned datasets are immutable, but its rag_qa
    # rows are not answerable from the corpus. Use v0.2 for retrieval runs.
    "golden_rag_v0.1": Path("datasets/golden/golden_rag_v0.1.jsonl"),
    "golden_rag_v0.2": Path("datasets/golden/golden_rag_v0.2.jsonl"),
    # Human-written questions and answers sampled from SQuAD v2, including its
    # adversarial unanswerable cases. Preferred over the synthetic sets when the
    # claim needs labels this project did not author.
    "golden_squad_v2_sampled": Path("datasets/squad_v2/golden.jsonl"),
    "golden_agentic_tools_v0.1": Path(
        "datasets/golden/golden_agentic_tools_v0.1.jsonl"
    ),
}


class CandidateGenerationRunConfig(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    run_id: str
    dataset_version: str
    provider_name: str
    model_name: str
    task_family: str = "rag"
    retrieval_mode: str = "hybrid_rrf_k60_top10_context4"
    prompt_version: str = "rag_prompt_v1"
    repeat_id: str = "repeat_01"
    matrix_id: str = "manual"
    expected_case_count: int | None = None


class CandidateGenerationRunSummary(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    run_id: str
    dataset_version: str
    provider_name: str
    model_name: str
    task_family: str
    retrieval_mode: str
    prompt_version: str
    repeat_id: str
    matrix_id: str
    output_path: str
    status_path: str
    total_cases: int
    already_completed_count: int
    generated_count: int
    skipped_count: int
    failed_count: int
    final_completed_count: int
    status: str


class CandidateGenerationError(Exception):
    pass


class Retriever(Protocol):
    def retrieve(self, query: str) -> list:
        ...


def build_run_id(
    matrix_id: str,
    provider: str,
    model: str,
    dataset_version: str,
    retrieval_mode: str,
    prompt_version: str,
    repeat_id: str,
) -> str:
    parts = [
        "cgen",
        matrix_id,
        provider,
        model,
        dataset_version,
        retrieval_mode,
        prompt_version,
        repeat_id,
    ]
    return "__".join(sanitize(part) for part in parts)


def sanitize(value: str) -> str:
    safe = []
    for char in value.lower():
        if char.isalnum():
            safe.append(char)
        else:
            safe.append("_")
    return "_".join("".join(safe).split("_"))


def candidate_answers_path(
    run_id: str,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> Path:
    return output_dir / f"{run_id}_candidate_answers.jsonl"


def candidate_status_path(
    run_id: str,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> Path:
    return output_dir / f"{run_id}_status.json"


def load_completed_case_ids(path: Path) -> set[str]:
    completed = set()
    if not path.exists():
        return completed

    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("status") == "completed" and isinstance(row.get("case_id"), str):
                completed.add(row["case_id"])

    return completed


def append_candidate_answer(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(row, ensure_ascii=True) + "\n")


def write_status(path: Path, summary: CandidateGenerationRunSummary) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(summary.model_dump_json(indent=2), encoding="utf-8")


# Providers whose output may be counted as a real candidate answer. Mock providers
# are excluded deliberately: they are useful for rehearsing the pipeline without
# spending money, but their answers must never enter a measured run. "self-hosted"
# is a real model served over HTTP, so it belongs here -- but it is a different
# claim from OpenAI/Anthropic API coverage and must be reported separately.
REAL_CANDIDATE_PROVIDERS = frozenset({"openai", "anthropic", "self-hosted"})


def resolve_provider(config: CandidateGenerationRunConfig) -> LLMProvider:
    if config.provider_name == "openai":
        return OpenAIProvider(model_name=config.model_name)
    if config.provider_name == "anthropic":
        return AnthropicProvider(model_name=config.model_name)
    if config.provider_name == "self-hosted":
        return SelfHostedProvider(model_name=config.model_name)

    raise CandidateGenerationError(
        f"Candidate generation only permits real providers "
        f"({', '.join(sorted(REAL_CANDIDATE_PROVIDERS))}), got {config.provider_name!r}. "
        "Mock providers are for rehearsal and must not enter a measured run."
    )


def build_retriever(retrieval_mode: str) -> Retriever:
    if retrieval_mode.startswith("bm25"):
        return ElasticsearchBm25Retriever()

    if retrieval_mode.startswith("dense"):
        return PostgresDenseRetriever(embedding_provider=OpenAIEmbeddingProvider())

    if retrieval_mode.startswith("hybrid"):
        dense = PostgresDenseRetriever(embedding_provider=OpenAIEmbeddingProvider())
        bm25 = ElasticsearchBm25Retriever()
        return HybridRetriever(dense_retriever=dense, bm25_retriever=bm25, rrf_k=RRF_K)

    raise CandidateGenerationError(f"Unsupported retrieval mode: {retrieval_mode}")


# Only retrieval-grounded tasks should receive retrieved context. The other task
# types evaluate model ability, prompt wording, judge behaviour, and run-to-run
# stability, none of which are answered by corpus chunks.
RETRIEVAL_TASK_TYPES = frozenset({TaskType.RAG_QA})


def case_requires_retrieval(case: EvalCase) -> bool:
    """Decide per case, not per run.

    A run configured as task_family="rag" previously applied retrieval to every
    case in the dataset. When the dataset mixes task types that handed support
    runbook chunks to arithmetic questions, which forced the model to refuse and
    made the resulting judge scores meaningless. A dataset row may override the
    default with an explicit metadata flag.
    """
    explicit = case.metadata.get("requires_retrieval")
    if isinstance(explicit, bool):
        return explicit
    return case.task_type in RETRIEVAL_TASK_TYPES


def build_request_for_case(
    config: CandidateGenerationRunConfig,
    case: EvalCase,
    retriever: Retriever | None,
) -> tuple[GenerationRequest, dict]:
    if config.task_family == "agentic_tool_calling":
        return (
            GenerationRequest(
                run_id=config.run_id,
                case_id=case.id,
                question=case.question,
            ),
            {"retrieved_chunk_ids": [], "generation_context_chunk_ids": []},
        )

    if retriever is None or not case_requires_retrieval(case):
        return build_rag_generation_request(
            run_id=config.run_id,
            case_id=case.id,
            question=case.question,
            retrieved_chunks=[],
        )

    return retrieve_context_and_build_rag_request(
        retriever=retriever,
        run_id=config.run_id,
        case_id=case.id,
        question=case.question,
    )


def generation_response_to_row(
    config: CandidateGenerationRunConfig,
    case: EvalCase,
    response: GenerationResponse,
    citation_fields: dict,
) -> dict:
    answer = CandidateAnswer(
        run_id=config.run_id,
        case_id=case.id,
        generated_answer=response.answer_text,
    )

    return {
        **answer.model_dump(mode="json"),
        "provider_name": response.provider_name,
        "model_name": response.model_name,
        "is_mock": response.is_mock,
        "dataset_version": config.dataset_version,
        "task_family": config.task_family,
        "retrieval_mode": config.retrieval_mode,
        "prompt_version": config.prompt_version,
        "repeat_id": config.repeat_id,
        "matrix_id": config.matrix_id,
        "metadata": {
            **response.metadata,
            **citation_fields,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "candidate_phase_only_not_judged": True,
        },
    }


def generate_candidate_answers_for_run(
    config: CandidateGenerationRunConfig,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    provider: LLMProvider | None = None,
    retriever: Retriever | None = None,
    concurrency: int = 1,
) -> CandidateGenerationRunSummary:
    """Generate a candidate answer per case, resuming from prior work.

    Fail-fast is deliberate and survives concurrency: a systematically broken config
    (wrong model name, exhausted credit) should stop immediately rather than spend
    money producing hundreds of identical failures. Under concurrency that becomes
    "stop submitting new work once any case has failed" -- in-flight requests still
    land, so nothing already paid for is discarded.
    """
    dataset_path = DATASET_PATHS.get(config.dataset_version)
    if dataset_path is None:
        raise CandidateGenerationError(f"Unknown dataset_version: {config.dataset_version}")
    if concurrency < 1:
        raise CandidateGenerationError("concurrency must be at least 1.")

    cases = load_eval_cases(dataset_path)
    if config.expected_case_count is not None and len(cases) != config.expected_case_count:
        raise CandidateGenerationError(
            f"Expected {config.expected_case_count} cases for {config.dataset_version}, got {len(cases)}."
        )

    output_path = candidate_answers_path(config.run_id, output_dir=output_dir)
    status_path = candidate_status_path(config.run_id, output_dir=output_dir)
    completed_case_ids = load_completed_case_ids(output_path)
    already_completed_count = len(completed_case_ids)

    provider = provider or resolve_provider(config)
    if retriever is None and config.task_family == "rag":
        retriever = build_retriever(config.retrieval_mode)

    tracer = get_tracer()
    pending = [case for case in cases if case.id not in completed_case_ids]

    write_lock = threading.Lock()
    stop = threading.Event()
    generated_count = 0
    failed_count = 0

    def generate_one(case: EvalCase) -> None:
        nonlocal generated_count, failed_count
        if stop.is_set():
            return

        try:
            with tracer.start_as_current_span("provider.generate_candidate_answer") as span:
                set_common_span_attributes(
                    span,
                    layer=SERVICE_LAYER_PROVIDER,
                    run_id=config.run_id,
                    trace_id=current_trace_id(),
                )
                span.set_attribute("eval.case_id", case.id)
                span.set_attribute("eval.dataset_version", config.dataset_version)
                span.set_attribute("llm.provider", config.provider_name)
                span.set_attribute("llm.model", config.model_name)
                span.set_attribute("eval.prompt_version", config.prompt_version)
                span.set_attribute("eval.concurrency", concurrency)

                with tracer.start_as_current_span("retrieval.fetch_context") as retrieval_span:
                    set_common_span_attributes(
                        retrieval_span,
                        layer=SERVICE_LAYER_RETRIEVAL,
                        run_id=config.run_id,
                    )
                    retrieval_span.set_attribute("eval.case_id", case.id)
                    retrieval_span.set_attribute("retrieval.strategy", config.retrieval_mode)
                    retrieval_span.set_attribute(
                        "retrieval.applied", case_requires_retrieval(case)
                    )
                    request, citation_fields = build_request_for_case(
                        config=config,
                        case=case,
                        retriever=retriever,
                    )
                    retrieval_span.set_attribute(
                        "retrieval.chunk_count",
                        len(citation_fields.get("retrieved_chunk_ids", [])),
                    )

                response = generate_answer(provider=provider, request=request)
                span.set_attribute("llm.answer_characters", len(response.answer_text))

                with tracer.start_as_current_span("storage.append_candidate_answer") as store_span:
                    set_common_span_attributes(
                        store_span,
                        layer=SERVICE_LAYER_STORAGE,
                        run_id=config.run_id,
                    )
                    store_span.set_attribute("eval.case_id", case.id)
                    store_span.set_attribute("eval.output_path", str(output_path))
                    row = generation_response_to_row(
                        config=config,
                        case=case,
                        response=response,
                        citation_fields=citation_fields,
                    )
        except Exception as error:  # noqa: BLE001 - recorded, then the run stops
            with write_lock:
                failed_count += 1
                append_candidate_answer(
                    output_path,
                    {
                        "run_id": config.run_id,
                        "case_id": case.id,
                        "generated_answer": "",
                        "status": "failed",
                        "provider_name": config.provider_name,
                        "model_name": config.model_name,
                        "is_mock": False,
                        "dataset_version": config.dataset_version,
                        "task_family": config.task_family,
                        "retrieval_mode": config.retrieval_mode,
                        "prompt_version": config.prompt_version,
                        "repeat_id": config.repeat_id,
                        "matrix_id": config.matrix_id,
                        "error": str(error),
                    },
                )
            stop.set()
            return

        with write_lock:
            append_candidate_answer(output_path, row)
            completed_case_ids.add(case.id)
            generated_count += 1
            write_status(
                status_path,
                build_summary(
                    config=config,
                    output_path=output_path,
                    status_path=status_path,
                    total_cases=len(cases),
                    already_completed_count=already_completed_count,
                    generated_count=generated_count,
                    failed_count=failed_count,
                    final_completed_count=len(completed_case_ids),
                ),
            )

    if concurrency == 1:
        for case in pending:
            generate_one(case)
            if stop.is_set():
                break
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            for _ in pool.map(generate_one, pending):
                pass

    summary = build_summary(
        config=config,
        output_path=output_path,
        status_path=status_path,
        total_cases=len(cases),
        already_completed_count=already_completed_count,
        generated_count=generated_count,
        failed_count=failed_count,
        final_completed_count=len(completed_case_ids),
    )
    write_status(status_path, summary)
    return summary


def build_summary(
    config: CandidateGenerationRunConfig,
    output_path: Path,
    status_path: Path,
    total_cases: int,
    already_completed_count: int,
    generated_count: int,
    failed_count: int,
    final_completed_count: int,
) -> CandidateGenerationRunSummary:
    status = "completed" if final_completed_count == total_cases and failed_count == 0 else "failed"
    if failed_count == 0 and final_completed_count < total_cases:
        status = "partial"

    return CandidateGenerationRunSummary(
        run_id=config.run_id,
        dataset_version=config.dataset_version,
        provider_name=config.provider_name,
        model_name=config.model_name,
        task_family=config.task_family,
        retrieval_mode=config.retrieval_mode,
        prompt_version=config.prompt_version,
        repeat_id=config.repeat_id,
        matrix_id=config.matrix_id,
        output_path=str(output_path),
        status_path=str(status_path),
        total_cases=total_cases,
        already_completed_count=already_completed_count,
        generated_count=generated_count,
        skipped_count=already_completed_count,
        failed_count=failed_count,
        final_completed_count=final_completed_count,
        status=status,
    )


def summarize_candidate_generation_outputs(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict:
    run_ids = set()
    completed_answers_by_provider: dict[str, int] = {}
    failed_answers_by_provider: dict[str, int] = {}
    failure_examples_by_provider: dict[str, str] = {}
    completed_answer_count = 0
    failed_answer_count = 0

    for path in output_dir.glob("*_candidate_answers.jsonl"):
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                run_id = row.get("run_id")
                if isinstance(run_id, str):
                    run_ids.add(run_id)
                if row.get("status") == "completed":
                    provider = row.get("provider_name", "unknown")
                    completed_answers_by_provider[provider] = (
                        completed_answers_by_provider.get(provider, 0) + 1
                    )
                    completed_answer_count += 1
                elif row.get("status") == "failed":
                    provider = row.get("provider_name", "unknown")
                    failed_answers_by_provider[provider] = (
                        failed_answers_by_provider.get(provider, 0) + 1
                    )
                    if provider not in failure_examples_by_provider:
                        failure_examples_by_provider[provider] = str(
                            row.get("error", "unknown error")
                        )
                    failed_answer_count += 1

    completed_run_count = 0
    for path in output_dir.glob("*_status.json"):
        try:
            status = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if status.get("status") == "completed":
            completed_run_count += 1

    return {
        "output_dir": str(output_dir),
        "actual_run_count": len(run_ids),
        "actual_completed_run_count": completed_run_count,
        "actual_candidate_answer_count": completed_answer_count,
        "failed_candidate_answer_count": failed_answer_count,
        "actual_candidate_answer_count_by_provider": completed_answers_by_provider,
        "failed_candidate_answer_count_by_provider": failed_answers_by_provider,
        "failure_examples_by_provider": failure_examples_by_provider,
    }
