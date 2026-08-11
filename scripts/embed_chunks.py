"""Embed corpus chunks with OpenAI and store the vectors in Postgres.

This spends real money, so it is checkpoint-resumable by construction: the set
of work remaining is derived from the database itself (`WHERE embedding IS
NULL`), not from a local progress file that can drift. Interrupting the script
and re-running it re-embeds nothing that already succeeded.

Each batch is committed before the next request is made. A crash mid-run loses
at most one batch.

Usage:
    python scripts/embed_chunks.py --estimate-only
    python scripts/embed_chunks.py
    python scripts/embed_chunks.py --limit 100      # partial run for rehearsal
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

from backend.app.embeddings import (  # noqa: E402
    EMBEDDING_DIMENSION,
    EmbeddingRequest,
    OpenAIEmbeddingProvider,
)

DEFAULT_DATABASE_URL = (
    "postgresql://llm_eval:llm_eval_dev_password@localhost:5433/llm_eval"
)
DEFAULT_BATCH_SIZE = 128
USD_PER_MILLION_TOKENS = 0.02


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def format_vector(values: list[float]) -> str:
    """pgvector accepts a bracketed literal; psycopg has no native adapter here."""
    return "[" + ",".join(repr(float(value)) for value in values) + "]"


def fetch_pending(connection, limit: int | None) -> list[tuple[str, str]]:
    query = (
        "SELECT id, text FROM chunks WHERE embedding IS NULL ORDER BY id"
    )
    if limit is not None:
        query += f" LIMIT {int(limit)}"
    with connection.cursor() as cursor:
        cursor.execute(query)
        return cursor.fetchall()


def counts(connection) -> tuple[int, int]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*), count(embedding) FROM chunks"
        )
        total, embedded = cursor.fetchone()
    return total, embedded


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--estimate-only",
        action="store_true",
        help="Report pending work and estimated cost without calling the API.",
    )
    args = parser.parse_args()

    with psycopg.connect(database_url()) as connection:
        total, embedded = counts(connection)
        pending = fetch_pending(connection, args.limit)

        pending_chars = sum(len(text) for _, text in pending)
        approx_tokens = pending_chars / 4
        estimated_cost = approx_tokens / 1_000_000 * USD_PER_MILLION_TOKENS

        print(f"chunks in database:    {total:,}")
        print(f"already embedded:      {embedded:,}")
        print(f"pending this run:      {len(pending):,}")
        print(f"approx tokens:         {approx_tokens:,.0f}")
        print(f"estimated cost:        ${estimated_cost:.4f}")

        if args.estimate_only:
            print("\n--estimate-only set; no API calls made.")
            return 0

        if not pending:
            print("\nNothing to embed. All chunks already have vectors.")
            return 0

        provider = OpenAIEmbeddingProvider()
        print(f"\nembedding with {provider.model_name} "
              f"({EMBEDDING_DIMENSION} dimensions)\n")

        started = time.monotonic()
        done = 0
        for start in range(0, len(pending), args.batch_size):
            batch = pending[start : start + args.batch_size]
            chunk_ids = [chunk_id for chunk_id, _ in batch]
            texts = [text for _, text in batch]

            response = provider.embed_texts(EmbeddingRequest(texts=texts))
            if len(response.embeddings) != len(batch):
                raise RuntimeError(
                    f"expected {len(batch)} embeddings, got {len(response.embeddings)}"
                )

            # Commit each batch before requesting the next one, so an
            # interruption costs at most this batch.
            with connection.cursor() as cursor:
                for chunk_id, vector in zip(chunk_ids, response.embeddings):
                    cursor.execute(
                        "UPDATE chunks SET embedding = %s::vector WHERE id = %s",
                        (format_vector(vector), chunk_id),
                    )
            connection.commit()

            done += len(batch)
            elapsed = time.monotonic() - started
            rate = done / elapsed if elapsed else 0
            remaining = (len(pending) - done) / rate if rate else 0
            print(
                f"  {done:,}/{len(pending):,} embedded  "
                f"({rate:.0f}/s, ~{remaining:.0f}s left)"
            )

        total, embedded = counts(connection)
        print(f"\ndone in {time.monotonic() - started:.1f}s")
        print(f"chunks with embeddings: {embedded:,} of {total:,}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
