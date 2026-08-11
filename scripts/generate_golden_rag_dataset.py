"""Generate a corpus-grounded RAG evaluation dataset.

golden_rag_v0.1 was written independently of the corpus: measured, 0 of its 120
questions contained any corpus vocabulary, so retrieval could never supply
relevant context. 115 of 120 candidate answers were correctly-refusing "the
context is insufficient" responses, and both judges failed every one. That made
the dual-judge slice degenerate rather than informative.

This dataset fixes the mismatch. Every answerable question targets a fact that
exists in exactly one document of the current corpus, and the expected answer is
that fact's value. The script verifies each expected answer actually appears in
the corpus before writing the row.

The set deliberately includes unanswerable questions. Those ask for a fact the
corpus does not contain, and the expected behaviour is abstention. Without them
a judge cannot distinguish a model that retrieves well from one that fabricates
confidently.

Usage:
    python scripts/generate_golden_rag_dataset.py
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
DEFAULT_OUTPUT_PATH = Path("datasets/golden/golden_rag_v0.2.jsonl")
DATASET_VERSION = "golden_rag_v0.2"
ANSWERABLE_COUNT = 108
UNANSWERABLE_COUNT = 12

ABSTENTION_ANSWER = (
    "The retrieved context does not contain this information."
)


def build_all_facts() -> list[DocumentFacts]:
    facts: list[DocumentFacts] = []
    global_index = 0
    for domain in sorted(DOMAIN_TOPICS):
        for position in range(DOCS_PER_DOMAIN):
            facts.append(DocumentFacts(domain, position, global_index))
            global_index += 1
    return facts


def load_document_text(path: Path) -> dict[str, str]:
    joined: dict[str, list[str]] = defaultdict(list)
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            chunk = json.loads(line)
            joined[chunk["document_id"]].append(chunk["text"])
    return {doc_id: "\n".join(texts) for doc_id, texts in joined.items()}


# Each probe returns (question, expected_answer, category, an anchor that must
# be present in the source document for the pair to be trustworthy).
def probes(f: DocumentFacts) -> list[tuple[str, str, str, str]]:
    return [
        (
            f"What is the escalation acknowledgement target for error {f.error_code}?",
            f"{f.sla_minutes} minutes",
            "exact_fact",
            f"acknowledgement target is {f.sla_minutes} minutes",
        ),
        (
            f"Which team owns escalations for error {f.error_code}?",
            f.owner_team,
            "exact_fact",
            f"Ownership sits with the {f.owner_team}",
        ),
        (
            f"How many days are results retained for the {f.workspace} workspace?",
            f"{f.retention_days} days",
            "single_hop",
            f"storage for {f.retention_days} days",
        ),
        (
            f"What per-minute call ceiling applies to {f.workspace} on the "
            f"{f.plan_tier} plan?",
            f"{f.rate_limit} calls per minute",
            "single_hop",
            f"{f.rate_limit} {f.procedure_slug} calls per minute",
        ),
        (
            f"What batch size does the resolution command for {f.error_code} use?",
            str(f.batch_size),
            "specificity",
            f"batch size of {f.batch_size}",
        ),
        (
            f"What retry backoff does the {f.procedure} resolution use for "
            f"{f.workspace}?",
            f"{f.backoff_ms} milliseconds",
            "specificity",
            f"a {f.backoff_ms} millisecond backoff",
        ),
        (
            f"What is the maximum number of rows allowed in one {f.procedure} "
            f"invocation for {f.workspace}?",
            f"{f.max_rows} rows",
            "lexical_gap",
            f"more than {f.max_rows} rows",
        ),
        (
            f"Which configuration key does runbook {f.runbook_ref} change?",
            f.config_key,
            "exact_fact",
            f.config_key,
        ),
        (
            f"How many approvals are required before editing {f.config_key}?",
            f"{f.approval_count}",
            "multi_hop",
            f"collect {f.approval_count} approval",
        ),
        (
            f"In which region is the {f.workspace} workspace hosted?",
            f.region,
            "single_hop",
            f"hosted in {f.region}",
        ),
        (
            f"When error {f.error_code} is mistaken for a permissions fault, what "
            f"distinguishes the two?",
            (
                f"A permissions fault leaves the {f.metric} counter flat, while "
                f"{f.error_code} drives it above {f.threshold_percent} percent."
            ),
            "distractor_robustness",
            f"permissions fault leaves `{f.metric}` flat",
        ),
        (
            f"After how many seconds does the {f.procedure} operation abort for "
            f"{f.workspace}?",
            f"{f.timeout_seconds} seconds",
            "single_hop",
            f"waited {f.timeout_seconds} seconds",
        ),
    ]


def unanswerable_probes(f: DocumentFacts) -> list[tuple[str, str, str, str]]:
    """Questions about facts the corpus deliberately does not record."""
    return [
        (
            f"What is the on-call engineer's phone number for error {f.error_code}?",
            ABSTENTION_ANSWER,
            "no_answer_abstention",
            "",
        ),
        (
            f"How much revenue did the {f.workspace} workspace generate last quarter?",
            ABSTENTION_ANSWER,
            "no_answer_abstention",
            "",
        ),
        (
            f"What database engine backs the {f.config_key} setting?",
            ABSTENTION_ANSWER,
            "no_answer_abstention",
            "",
        ),
    ]


class DatasetBuildError(RuntimeError):
    pass


def build_rows(
    all_facts: list[DocumentFacts], document_text: dict[str, str]
) -> list[dict]:
    rows: list[dict] = []
    stride = 13
    case_number = 0

    # Answerable rows: walk the corpus, cycling through probe types so no single
    # fact shape dominates the dataset.
    probe_count = len(probes(all_facts[0]))
    for index in range(ANSWERABLE_COUNT):
        facts = all_facts[(index * stride) % len(all_facts)]
        question, expected, category, anchor = probes(facts)[index % probe_count]

        body = document_text.get(facts.doc_id)
        if body is None:
            raise DatasetBuildError(f"{facts.doc_id} missing from corpus")
        if anchor and anchor not in body:
            raise DatasetBuildError(
                f"anchor {anchor!r} absent from {facts.doc_id}; question would be "
                "unanswerable from the corpus"
            )

        case_number += 1
        rows.append(
            {
                "id": f"RG-{case_number:03d}",
                "question": question,
                "expected_answer": expected,
                "task_type": "rag_qa",
                "metadata": {
                    "dataset_version": DATASET_VERSION,
                    "dimension": "retrieval_quality",
                    "category": category,
                    "answerable": True,
                    "source_document_id": facts.doc_id,
                    "runbook_ref": facts.runbook_ref,
                    "requires_retrieval": True,
                    "scoring": "judge_rubric",
                },
            }
        )

    # Unanswerable rows, spread across documents far from the answerable stride.
    unanswerable_probe_count = len(unanswerable_probes(all_facts[0]))
    for index in range(UNANSWERABLE_COUNT):
        facts = all_facts[(index * 89 + 41) % len(all_facts)]
        question, expected, category, _ = unanswerable_probes(facts)[
            index % unanswerable_probe_count
        ]
        case_number += 1
        rows.append(
            {
                "id": f"RG-{case_number:03d}",
                "question": question,
                "expected_answer": expected,
                "task_type": "rag_qa",
                "metadata": {
                    "dataset_version": DATASET_VERSION,
                    "dimension": "retrieval_quality",
                    "category": category,
                    "answerable": False,
                    "source_document_id": facts.doc_id,
                    "runbook_ref": facts.runbook_ref,
                    "requires_retrieval": True,
                    "scoring": "judge_rubric",
                },
            }
        )

    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()

    all_facts = build_all_facts()
    document_text = load_document_text(args.chunks)
    rows = build_rows(all_facts, document_text)

    ids = [row["id"] for row in rows]
    if len(set(ids)) != len(ids):
        raise DatasetBuildError("duplicate case IDs")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")

    answerable = sum(1 for row in rows if row["metadata"]["answerable"])
    categories: dict[str, int] = defaultdict(int)
    for row in rows:
        categories[row["metadata"]["category"]] += 1

    print(f"wrote {len(rows)} cases to {args.output}")
    print(f"  answerable from corpus: {answerable}")
    print(f"  expecting abstention:   {len(rows) - answerable}")
    print("  categories:")
    for category in sorted(categories):
        print(f"    {category}: {categories[category]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
