import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from pydantic import BaseModel
import argparse
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

from backend.app.bm25_retrieval import ElasticsearchBm25Retriever
from backend.app.dense_retrieval import PostgresDenseRetriever
from backend.app.embeddings import OpenAIEmbeddingProvider
from backend.app.hybrid_retrieval import HybridRetriever
from backend.app.dataset_loader import load_eval_cases
from backend.app.eval_run import CandidateAnswer
from backend.app.generation import (
    build_rag_generation_request,
    generate_answer,
    retrieve_context_and_build_rag_request,
)
from backend.app.providers import get_provider


DATASET_PATH = Path("datasets/golden/golden_rag_v0.1.jsonl")


class LocalMockGenerationSummary(BaseModel):
    run_id: str
    dataset_path: Path
    cases_loaded: int
    candidate_answers_saved: int
    output_path: Path

def create_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"local_mock_{timestamp}"

def build_hybrid_retriever() -> HybridRetriever:
    embedding_provider = OpenAIEmbeddingProvider()
    dense_retriever = PostgresDenseRetriever(
        embedding_provider=embedding_provider,
    )
    bm25_retriever = ElasticsearchBm25Retriever()

    return HybridRetriever(
        dense_retriever=dense_retriever,
        bm25_retriever=bm25_retriever,
    )

def run_local_mock_generation(
    dataset_path: Path = DATASET_PATH,
    output_dir: Path = Path("runs"),
    run_id: str | None = None,
    provider_name: str = "mock",
    retrieved_chunks_by_case_id: dict | None = None,
    retriever=None,
    context_token_budget: int = 2_000,
    case_limit: int | None = None,
) -> LocalMockGenerationSummary:
    if run_id is None:
        run_id = create_run_id()
    
    cases = load_eval_cases(dataset_path)
    if case_limit is not None:
        cases = cases[:case_limit]
    provider = get_provider(provider_name)

    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / f"{run_id}_candidate_answers.jsonl"
    saved_count = 0

    with output_path.open("w", encoding="utf-8") as file:
        for case in cases:
            if retriever is not None:
                request, citation_fields = retrieve_context_and_build_rag_request(
                    retriever=retriever,
                    run_id=run_id,
                    case_id=case.id,
                    question=case.question,
                    context_token_budget=context_token_budget,
                )
            else:
                retrieved_chunks = []
                if retrieved_chunks_by_case_id is not None:
                    retrieved_chunks = retrieved_chunks_by_case_id.get(case.id, [])

                request, citation_fields = build_rag_generation_request(
                    run_id=run_id,
                    case_id=case.id,
                    question=case.question,
                    retrieved_chunks=retrieved_chunks,
                    context_token_budget=context_token_budget,
                )

            response = generate_answer(provider, request)

            candidate = CandidateAnswer(
                run_id=run_id,
                case_id=case.id,
                generated_answer=response.answer_text,
            )

            row = {
                "run_id": candidate.run_id,
                "case_id": candidate.case_id,
                "generated_answer": candidate.generated_answer,
                "status": candidate.status.value,
                "provider_name": response.provider_name,
                "model_name": response.model_name,
                "is_mock": response.is_mock,
                "metadata": {
                    **response.metadata,
                    **citation_fields,
                },
            }

            file.write(json.dumps(row) + "\n")
            saved_count += 1

    return LocalMockGenerationSummary(
        run_id=run_id,
        dataset_path=dataset_path,
        cases_loaded=len(cases),
        candidate_answers_saved=saved_count,
        output_path=output_path,
    )

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--provider",
        default="mock",
        choices=["mock", "openai", "anthropic", "self-hosted"],
        help="Candidate answer provider to use.",
    )
    parser.add_argument(
        "--use-hybrid-retrieval",
        action="store_true",
        help="Retrieve hybrid top 10 context for each case before generation.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit the number of cases generated for rehearsal runs.",
    )
    return parser.parse_args()

def main() -> None:
    args = parse_args()

    retriever = None
    if args.use_hybrid_retrieval:
        retriever = build_hybrid_retriever()

    summary = run_local_mock_generation(
        provider_name=args.provider,
        retriever=retriever,
        case_limit=args.limit,
    )

    print(f"run_id={summary.run_id}")
    print(f"dataset={summary.dataset_path}")
    print(f"cases_loaded={summary.cases_loaded}")
    print(f"candidate_answers_saved={summary.candidate_answers_saved}")
    print(f"output_path={summary.output_path}")


if __name__ == "__main__":
    main()