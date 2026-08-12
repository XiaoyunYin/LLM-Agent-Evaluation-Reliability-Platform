"""Build a corpus-grounded RAG evaluation set from SQuAD v2.

BEIR supplies human relevance judgments but not reference answers, so it can score
retrieval and nothing downstream. A generation and judging eval needs
(question, reference answer, supporting passage), and SQuAD v2 has all three
written by people.

It also ships genuinely unanswerable questions (`is_impossible`), written by
annotators who saw the passage and deliberately asked something it does not
answer. Those are far better abstention cases than any this project could invent:
a synthetic "what is the on-call phone number" is obviously unanswerable, while a
SQuAD adversarial question looks answerable and is not. That distinction is what
separates a model that reads its context from one that pattern-matches.

Three files are produced, all in this project's existing schemas:

- `chunks.jsonl`  - one chunk per unique SQuAD paragraph
- `golden.jsonl`  - EvalCase rows with human questions and human answers
- `labels.jsonl`  - retrieval labels; the relevant chunk is the paragraph the
                    annotator wrote the question against

Sampling is seeded, so the same seed reproduces the same evaluation set.

Usage:
    python scripts/load_squad_dataset.py
    python scripts/load_squad_dataset.py --questions 240 --seed 7
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from urllib.request import urlopen

SQUAD_DEV_URL = "https://rajpurkar.github.io/SQuAD-explorer/dataset/dev-v2.0.json"
OUTPUT_DIR = Path("datasets/squad_v2")
DOWNLOAD_PATH = OUTPUT_DIR / "_download" / "dev-v2.0.json"

DATASET_VERSION = "golden_squad_v2_sampled"
PROTOCOL_VERSION = "squad_v2_paragraph_provenance_v1"
DEFAULT_QUESTIONS = 120
DEFAULT_SEED = 20260811
# SQuAD v2 dev is roughly half unanswerable. Holding the eval set at one third
# keeps abstention well represented without letting it dominate the score.
UNANSWERABLE_FRACTION = 1 / 3

ABSTENTION_ANSWER = "The retrieved context does not contain this information."

LABELING_LIMITATIONS = [
    "relevance_derived_from_squad_paragraph_provenance",
    "single_relevant_paragraph_per_question",
    "other_paragraphs_may_also_support_the_answer",
    "questions_and_answers_written_by_human_annotators",
]


def download(url: str, destination: Path) -> dict:
    if destination.exists():
        print(f"already downloaded: {destination}")
        return json.loads(destination.read_text(encoding="utf-8"))

    print(f"downloading {url}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urlopen(url, timeout=120) as response:  # noqa: S310 - fixed, trusted host
        payload = response.read()
    print(f"  {len(payload):,} bytes")
    destination.write_bytes(payload)
    return json.loads(payload.decode("utf-8"))


def paragraph_id(context: str) -> str:
    """Stable ID from the paragraph text, so the same paragraph always maps to the
    same chunk even across runs and sample sizes."""
    digest = hashlib.sha1(context.encode("utf-8")).hexdigest()[:16]
    return f"squad_p_{digest}"


def build(raw: dict) -> tuple[list[dict], list[dict]]:
    """Return (chunks, question_records) for the whole dev set."""
    chunks_by_id: dict[str, dict] = {}
    questions: list[dict] = []

    for article in raw["data"]:
        title = article.get("title", "")
        for paragraph in article["paragraphs"]:
            context = paragraph["context"].strip()
            if not context:
                continue
            chunk_id = paragraph_id(context)
            if chunk_id not in chunks_by_id:
                chunks_by_id[chunk_id] = {
                    "id": chunk_id,
                    "document_id": chunk_id,
                    "chunk_index": 0,
                    "text": context,
                    "metadata": {
                        "source_path": "squad_v2:dev",
                        "title": title.replace("_", " "),
                        "category": "squad_v2",
                        "chunk_size": len(context),
                        "chunk_overlap": 0,
                    },
                }

            for qa in paragraph["qas"]:
                question = qa["question"].strip()
                if not question:
                    continue
                answers = [a["text"].strip() for a in qa.get("answers", [])]
                # Prefer the most frequently given answer; annotators disagree.
                best = ""
                if answers:
                    best = max(set(answers), key=answers.count)
                questions.append(
                    {
                        "squad_id": qa["id"],
                        "question": question,
                        "answer": best,
                        "answerable": not qa.get("is_impossible", False) and bool(best),
                        "chunk_id": chunk_id,
                        "title": title.replace("_", " "),
                    }
                )

    return list(chunks_by_id.values()), questions


def sample(
    questions: list[dict], total: int, seed: int
) -> list[dict]:
    answerable = [q for q in questions if q["answerable"]]
    unanswerable = [q for q in questions if not q["answerable"]]

    want_unanswerable = round(total * UNANSWERABLE_FRACTION)
    want_answerable = total - want_unanswerable

    rng = random.Random(seed)
    if len(answerable) < want_answerable or len(unanswerable) < want_unanswerable:
        raise ValueError(
            f"not enough questions: have {len(answerable)} answerable / "
            f"{len(unanswerable)} unanswerable, need {want_answerable}/{want_unanswerable}"
        )

    picked = rng.sample(answerable, want_answerable) + rng.sample(
        unanswerable, want_unanswerable
    )
    rng.shuffle(picked)
    return picked


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=int, default=DEFAULT_QUESTIONS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()

    raw = download(SQUAD_DEV_URL, DOWNLOAD_PATH)
    chunks, questions = build(raw)
    print(f"dev set: {len(chunks):,} unique paragraphs, {len(questions):,} questions")

    picked = sample(questions, args.questions, args.seed)

    golden_rows = []
    label_rows = []
    for index, item in enumerate(picked, start=1):
        case_id = f"SQ-{index:03d}"
        answerable = item["answerable"]
        golden_rows.append(
            {
                "id": case_id,
                "question": item["question"],
                "expected_answer": item["answer"] if answerable else ABSTENTION_ANSWER,
                "task_type": "rag_qa",
                "metadata": {
                    "dataset_version": DATASET_VERSION,
                    "dimension": "retrieval_quality",
                    "category": "extractive_qa" if answerable else "no_answer_abstention",
                    "answerable": answerable,
                    "source_document_id": item["chunk_id"],
                    "squad_id": item["squad_id"],
                    "article_title": item["title"],
                    "requires_retrieval": True,
                    "scoring": "judge_rubric",
                },
            }
        )
        # Unanswerable questions still have a provenance paragraph - the annotator
        # wrote them against it - so retrieval is still expected to surface it.
        label_rows.append(
            {
                "id": case_id,
                "query": item["question"],
                "split": "heldout",
                "labeling_protocol_version": PROTOCOL_VERSION,
                "labels_created_blind_to_judge_outputs": True,
                "categories": {
                    "domain": "squad_v2",
                    "hop_type": "single-hop",
                    "match_type": "semantic/paraphrase",
                    "difficulty": "hard" if not answerable else "easy",
                },
                "relevant_chunks": [
                    {
                        "chunk_id": item["chunk_id"],
                        "relevance": 2,
                        "note": (
                            "Paragraph the SQuAD annotator wrote this question against."
                        ),
                    }
                ],
                "labeling_limitations": LABELING_LIMITATIONS,
            }
        )

    write_jsonl(args.output_dir / "chunks.jsonl", chunks)
    write_jsonl(args.output_dir / "golden.jsonl", golden_rows)
    write_jsonl(args.output_dir / "labels.jsonl", label_rows)

    answerable_count = sum(1 for r in golden_rows if r["metadata"]["answerable"])
    print()
    print(f"sampled {len(golden_rows)} questions with seed {args.seed}")
    print(f"  answerable          : {answerable_count}")
    print(f"  expecting abstention: {len(golden_rows) - answerable_count}")
    print(f"  distinct paragraphs referenced: "
          f"{len({r['metadata']['source_document_id'] for r in golden_rows})}")
    print()
    print(f"wrote {args.output_dir / 'chunks.jsonl'}  ({len(chunks):,} chunks)")
    print(f"wrote {args.output_dir / 'golden.jsonl'}")
    print(f"wrote {args.output_dir / 'labels.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
