"""Run one candidate-generation configuration directly, without Redis or a worker.

The matrix submission path (`submit_candidate_run_matrix.py`) exists for many runs
and needs Redis plus a worker process. For a single 120-case configuration that is
more moving parts than the job requires, and the extra machinery is one more thing
that can fail between paying for tokens and persisting the answers.

Resume behaviour is unchanged: completed case IDs are read back from the output
JSONL, so re-running skips work already paid for.

Usage:
    python scripts/generate_candidates_for_dataset.py \
        --dataset golden_squad_v2_sampled \
        --provider openai --model gpt-4o-mini \
        --index squad_v2_chunks

    python scripts/generate_candidates_for_dataset.py \
        --dataset golden_squad_v2_sampled \
        --provider self-hosted --model mistral-7b-instruct-v0.3-awq \
        --index squad_v2_chunks
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.bm25_retrieval import ElasticsearchBm25Retriever  # noqa: E402
from backend.app.candidate_generation import (  # noqa: E402
    DEFAULT_OUTPUT_DIR,
    CandidateGenerationRunConfig,
    build_run_id,
    generate_candidate_answers_for_run,
)
from backend.app.dense_retrieval import PostgresDenseRetriever  # noqa: E402
from backend.app.embeddings import OpenAIEmbeddingProvider  # noqa: E402
from backend.app.hybrid_retrieval import RRF_K, HybridRetriever  # noqa: E402


def build_retriever(retrieval_mode: str, index_name: str | None):
    """Same shapes as the library builder, but with an explicit index so a run can
    target one corpus while another sits in the default index."""
    bm25 = ElasticsearchBm25Retriever(index_name=index_name)
    if retrieval_mode.startswith("bm25"):
        return bm25
    dense = PostgresDenseRetriever(embedding_provider=OpenAIEmbeddingProvider())
    if retrieval_mode.startswith("dense"):
        return dense
    return HybridRetriever(dense_retriever=dense, bm25_retriever=bm25, rrf_k=RRF_K)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--retrieval-mode", default="hybrid_rrf_k60_top10_context4")
    parser.add_argument("--prompt-version", default="rag_prompt_v1")
    parser.add_argument("--repeat-id", default="repeat_01")
    parser.add_argument("--matrix-id", default="dual_judge_slice_v1")
    parser.add_argument("--index", default=None, help="Elasticsearch index to search.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Parallel in-flight generations. Raising this is what makes a "
             "self-hosted scale run affordable in GPU hours.",
    )
    parser.add_argument(
        "--allow-paid-api",
        action="store_true",
        help="Required for openai/anthropic. Spending money should be explicit.",
    )
    args = parser.parse_args()

    if args.provider in {"openai", "anthropic"} and not args.allow_paid_api:
        print(
            f"{args.provider} is a paid API. Re-run with --allow-paid-api to confirm.",
            file=sys.stderr,
        )
        return 2

    if args.provider == "self-hosted" and not os.getenv("SELF_HOSTED_MODEL_ENDPOINT"):
        print(
            "SELF_HOSTED_MODEL_ENDPOINT is not set. Point it at the vLLM endpoint "
            "before running self-hosted generation.",
            file=sys.stderr,
        )
        return 2

    run_id = build_run_id(
        matrix_id=args.matrix_id,
        provider=args.provider,
        model=args.model,
        dataset_version=args.dataset,
        retrieval_mode=args.retrieval_mode,
        prompt_version=args.prompt_version,
        repeat_id=args.repeat_id,
    )
    config = CandidateGenerationRunConfig(
        run_id=run_id,
        dataset_version=args.dataset,
        provider_name=args.provider,
        model_name=args.model,
        task_family="rag",
        retrieval_mode=args.retrieval_mode,
        prompt_version=args.prompt_version,
        repeat_id=args.repeat_id,
        matrix_id=args.matrix_id,
    )

    print(f"run_id: {run_id}")
    summary = generate_candidate_answers_for_run(
        config=config,
        output_dir=args.output_dir,
        retriever=build_retriever(args.retrieval_mode, args.index),
        concurrency=args.concurrency,
    )

    print(f"total_cases:            {summary.total_cases}")
    print(f"already_completed:      {summary.already_completed_count}")
    print(f"generated_this_run:     {summary.generated_count}")
    print(f"failed:                 {summary.failed_count}")
    print(f"final_completed_count:  {summary.final_completed_count}")
    print(f"status:                 {summary.status}")
    print(f"output: {summary.output_path}")
    return 0 if summary.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
