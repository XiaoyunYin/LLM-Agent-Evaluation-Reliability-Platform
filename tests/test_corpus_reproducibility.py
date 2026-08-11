"""Guard that the committed corpus still matches what the generator produces.

The generator was once edited after the corpus had been written, and both were
committed together. Nothing failed: the corpus on disk was simply no longer the
corpus the code produced, so every retrieval measurement described a fixture that
could not be rebuilt. The drift was one sentence in one of four document types
and was only noticed by regenerating and diffing by hand.

These tests rebuild documents in memory and compare them against the committed
files, so generator drift fails here instead of silently invalidating a benchmark.
"""

from pathlib import Path

import pytest

from scripts.generate_synthetic_corpus import (
    DOCS_PER_DOMAIN,
    DOC_TYPES,
    DOMAIN_TOPICS,
    DocumentFacts,
    build_document,
)

RAW_DIR = Path("datasets/corpus/raw")


def all_facts() -> list[DocumentFacts]:
    facts = []
    global_index = 0
    for domain in sorted(DOMAIN_TOPICS):
        for position in range(DOCS_PER_DOMAIN):
            facts.append(DocumentFacts(domain, position, global_index))
            global_index += 1
    return facts


def test_generator_reproduces_committed_documents_of_every_type():
    """One document per type. The drift that slipped through affected exactly one
    type, so sampling a single document would have missed it."""
    facts_by_type: dict[str, DocumentFacts] = {}
    for facts in all_facts():
        facts_by_type.setdefault(facts.doc_type, facts)

    assert set(facts_by_type) == set(DOC_TYPES)

    for doc_type, facts in sorted(facts_by_type.items()):
        committed = RAW_DIR / f"{facts.doc_id}.md"
        if not committed.exists():
            pytest.skip(f"corpus not generated: {committed} missing")
        assert build_document(facts) == committed.read_text(encoding="utf-8"), (
            f"{doc_type} document {facts.doc_id} drifted from the committed corpus. "
            "Regenerate with scripts/generate_synthetic_corpus.py --clean, then "
            "re-index, re-embed, and re-run the retrieval benchmark."
        )


def test_generation_is_deterministic():
    """Same inputs, same bytes. Reproducibility is what lets a measurement be
    rebuilt from source rather than trusted because it is checked in."""
    facts = all_facts()[0]
    assert build_document(facts) == build_document(facts)

    rebuilt = DocumentFacts(facts.domain, 0, 0)
    assert build_document(rebuilt) == build_document(facts)


def test_document_count_matches_committed_corpus():
    if not RAW_DIR.exists():
        pytest.skip("corpus not generated")
    expected = len(DOMAIN_TOPICS) * DOCS_PER_DOMAIN
    assert len(list(RAW_DIR.glob("*.md"))) == expected
