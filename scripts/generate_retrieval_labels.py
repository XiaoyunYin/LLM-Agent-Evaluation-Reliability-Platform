"""Generate the held-out retrieval label set from the corpus.

Labels are *derived*, not asserted. For every query the script knows which fact
answers it, then searches the corpus for the chunk that actually contains that
fact. If the answer text is not found in exactly the expected document the
script fails loudly rather than emitting a label that points at the wrong chunk.

Relevance is graded:
  2 - the chunk containing the answer
  1 - another chunk from the same document that shares the topic but does not
      answer the question

That distinction is what makes nDCG@10 report something recall@10 does not,
since ndcg_at_k weights gains as 2**relevance - 1.

The 120 queries are balanced across 8 category cells of 15:
difficulty (easy/hard) x hop type (single/multi) x match type (exact/semantic).

Usage:
    python scripts/generate_retrieval_labels.py
    python scripts/generate_retrieval_labels.py --output datasets/labels/custom.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

from scripts.generate_synthetic_corpus import (  # noqa: E402
    DOCS_PER_DOMAIN,
    DOMAIN_TOPICS,
    DocumentFacts,
)

DEFAULT_CHUNKS_PATH = Path("datasets/corpus/chunks.jsonl")
DEFAULT_OUTPUT_PATH = Path("datasets/labels/retrieval_heldout_120_v0.2.jsonl")
PROTOCOL_VERSION = "retrieval_labels_v0.2"
PER_CELL = 15
MAX_PARTIAL_CHUNKS = 1

LABELING_LIMITATIONS = [
    "synthetic_corpus",
    "labels_derived_programmatically_from_known_document_facts",
    "not_exhaustively_judged_against_every_chunk",
    "single_annotator_protocol",
]


def build_all_facts() -> list[DocumentFacts]:
    facts: list[DocumentFacts] = []
    global_index = 0
    for domain in sorted(DOMAIN_TOPICS):
        for position in range(DOCS_PER_DOMAIN):
            facts.append(DocumentFacts(domain, position, global_index))
            global_index += 1
    return facts


def load_chunks_by_document(path: Path) -> dict[str, list[dict]]:
    by_document: dict[str, list[dict]] = defaultdict(list)
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            chunk = json.loads(line)
            by_document[chunk["document_id"]].append(chunk)
    for chunks in by_document.values():
        chunks.sort(key=lambda c: c["chunk_index"])
    return dict(by_document)


def find_answer_chunks(chunks: list[dict], anchor: str) -> list[str]:
    """Return IDs of chunks containing the anchor text. Chunks overlap, so an
    anchor can legitimately land in more than one."""
    return [chunk["id"] for chunk in chunks if anchor in chunk["text"]]


def find_partial_chunks(
    chunks: list[dict], facts: DocumentFacts, exclude: set[str]
) -> list[str]:
    """Same-document chunks that mention the document's identity but do not
    contain the answer. These are the grade-1 partials."""
    partials = [
        chunk["id"]
        for chunk in chunks
        if chunk["id"] not in exclude
        and (facts.error_code in chunk["text"] or facts.workspace_slug in chunk["text"])
    ]
    return partials[:MAX_PARTIAL_CHUNKS]


# Anchors must satisfy two properties, both verified empirically before use:
#
#   1. Universal across document types. runbook, postmortem, reference, and faq
#      word their prose differently, so a type-specific phrase silently fails.
#   2. Document-unique. Measured over 1,100 documents: config_key, error_code,
#      workspace_slug, backoff_ms, and max_rows are unique 1100/1100. retention_days
#      is shared by up to 40 documents and owner_team by up to 100 - anchoring on
#      those marks one document relevant while dozens hold the identical fact,
#      which is the duplicate-cluster defect of corpus v0.2 in miniature.
#
# Only the unique fields are used below. Query phrasing carries the exact-term vs
# semantic distinction; the anchor only locates the answer.
def q_easy_exact(f: DocumentFacts) -> tuple[str, str]:
    return (
        f"What retry backoff is used when resolving error {f.error_code}?",
        f"{f.backoff_ms} millisecond",
    )


def q_easy_semantic(f: DocumentFacts) -> tuple[str, str]:
    return (
        f"How long does the {f.workspace} workspace pause between retry "
        "attempts when a run fails?",
        f"{f.backoff_ms} millisecond",
    )


def q_hard_exact(f: DocumentFacts) -> tuple[str, str]:
    return (
        f"What row cap does the setting `{f.config_key}` enforce?",
        f"{f.max_rows} row",
    )


def q_hard_semantic(f: DocumentFacts) -> tuple[str, str]:
    return (
        f"What is the largest payload {f.workspace} can submit in a single "
        f"{f.procedure_slug} run?",
        f"{f.max_rows} row",
    )


def q_multi_easy_exact(f: DocumentFacts) -> tuple[str, str]:
    return (
        f"the retry backoff for error {f.error_code}",
        f"{f.backoff_ms} millisecond",
    )


def q_multi_easy_semantic(f: DocumentFacts) -> tuple[str, str]:
    return (
        f"how long {f.workspace} waits between retries",
        f"{f.backoff_ms} millisecond",
    )


def q_multi_hard_exact(f: DocumentFacts) -> tuple[str, str]:
    return (f"the row cap enforced by `{f.config_key}`", f"{f.max_rows} row")


def q_multi_hard_semantic(f: DocumentFacts) -> tuple[str, str]:
    return (
        f"the largest payload {f.workspace} accepts in one run",
        f"{f.max_rows} row",
    )


SINGLE_HOP_BUILDERS = {
    ("easy", "exact-term"): q_easy_exact,
    ("easy", "semantic/paraphrase"): q_easy_semantic,
    ("hard", "exact-term"): q_hard_exact,
    ("hard", "semantic/paraphrase"): q_hard_semantic,
}

MULTI_HOP_BUILDERS = {
    ("easy", "exact-term"): q_multi_easy_exact,
    ("easy", "semantic/paraphrase"): q_multi_easy_semantic,
    ("hard", "exact-term"): q_multi_hard_exact,
    ("hard", "semantic/paraphrase"): q_multi_hard_semantic,
}

MULTI_HOP_PREFIX = {
    ("easy", "exact-term"): "Compare",
    ("easy", "semantic/paraphrase"): "Compare",
    ("hard", "exact-term"): "Compare",
    ("hard", "semantic/paraphrase"): "Compare",
}


class LabelBuildError(RuntimeError):
    pass


def build_relevant_chunks(
    facts: DocumentFacts,
    chunks_by_document: dict[str, list[dict]],
    anchor: str,
    note: str,
) -> list[dict]:
    chunks = chunks_by_document.get(facts.doc_id)
    if not chunks:
        raise LabelBuildError(f"{facts.doc_id} has no chunks")

    answer_ids = find_answer_chunks(chunks, anchor)
    if not answer_ids:
        raise LabelBuildError(
            f"anchor {anchor!r} not found in any chunk of {facts.doc_id}"
        )

    relevant = [
        {"chunk_id": chunk_id, "relevance": 2, "note": note} for chunk_id in answer_ids
    ]
    for partial_id in find_partial_chunks(chunks, facts, set(answer_ids)):
        relevant.append(
            {
                "chunk_id": partial_id,
                "relevance": 1,
                "note": (
                    f"Same runbook {facts.runbook_ref} and mentions "
                    f"{facts.error_code}, but does not contain the answer."
                ),
            }
        )
    return relevant


def generate_labels(
    all_facts: list[DocumentFacts], chunks_by_document: dict[str, list[dict]]
) -> list[dict]:
    records: list[dict] = []
    # Stride through the corpus so consecutive queries hit different domains and
    # no document is reused across cells.
    cursor = 0
    stride = 7
    used: set[str] = set()

    def next_facts() -> DocumentFacts:
        nonlocal cursor
        while True:
            facts = all_facts[(cursor * stride) % len(all_facts)]
            cursor += 1
            if facts.doc_id not in used:
                used.add(facts.doc_id)
                return facts

    label_number = 0
    for difficulty in ("easy", "hard"):
        for hop_type in ("single-hop", "multi-hop"):
            for match_type in ("exact-term", "semantic/paraphrase"):
                for _ in range(PER_CELL):
                    label_number += 1
                    label_id = f"RH-{label_number:03d}"

                    if hop_type == "single-hop":
                        facts = next_facts()
                        builder = SINGLE_HOP_BUILDERS[(difficulty, match_type)]
                        query, anchor = builder(facts)
                        relevant = build_relevant_chunks(
                            facts,
                            chunks_by_document,
                            anchor,
                            f"Directly answers the question in runbook {facts.runbook_ref}.",
                        )
                        domain = facts.domain
                    else:
                        facts_a = next_facts()
                        facts_b = next_facts()
                        builder = MULTI_HOP_BUILDERS[(difficulty, match_type)]
                        clause_a, anchor_a = builder(facts_a)
                        clause_b, anchor_b = builder(facts_b)
                        prefix = MULTI_HOP_PREFIX[(difficulty, match_type)]
                        query = f"{prefix} {clause_a} with {clause_b}."
                        relevant = build_relevant_chunks(
                            facts_a,
                            chunks_by_document,
                            anchor_a,
                            f"Answers the first half of the comparison ({facts_a.runbook_ref}).",
                        ) + build_relevant_chunks(
                            facts_b,
                            chunks_by_document,
                            anchor_b,
                            f"Answers the second half of the comparison ({facts_b.runbook_ref}).",
                        )
                        domain = facts_a.domain

                    records.append(
                        {
                            "id": label_id,
                            "query": query,
                            "split": "heldout",
                            "labeling_protocol_version": PROTOCOL_VERSION,
                            "labels_created_blind_to_judge_outputs": True,
                            "categories": {
                                "difficulty": difficulty,
                                "hop_type": hop_type,
                                "match_type": match_type,
                                "domain": domain,
                            },
                            "relevant_chunks": relevant,
                            "labeling_limitations": LABELING_LIMITATIONS,
                        }
                    )
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()

    all_facts = build_all_facts()
    chunks_by_document = load_chunks_by_document(args.chunks)
    known_chunk_ids = {
        chunk["id"] for chunks in chunks_by_document.values() for chunk in chunks
    }

    records = generate_labels(all_facts, chunks_by_document)

    # Every emitted chunk ID must exist. A label pointing at a missing chunk is
    # worse than no label, because it silently depresses recall.
    for record in records:
        for relevant in record["relevant_chunks"]:
            if relevant["chunk_id"] not in known_chunk_ids:
                raise LabelBuildError(
                    f"{record['id']} references unknown chunk {relevant['chunk_id']}"
                )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")

    grades: dict[int, int] = defaultdict(int)
    for record in records:
        for relevant in record["relevant_chunks"]:
            grades[relevant["relevance"]] += 1

    print(f"wrote {len(records)} labeled queries to {args.output}")
    print(f"relevant chunk references: {sum(grades.values())}")
    for grade in sorted(grades, reverse=True):
        print(f"  relevance {grade}: {grades[grade]}")
    print(f"documents used: {len({r['id'] for r in records})} queries over "
          f"{len({c['chunk_id'].rsplit('_chunk_', 1)[0] for r in records for c in r['relevant_chunks']})} documents")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
