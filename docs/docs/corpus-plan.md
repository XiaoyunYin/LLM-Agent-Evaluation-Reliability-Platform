# Corpus Plan

## Domain

The retrieval corpus will use fictional SaaS analytics support and operations documents. The documents will cover topics such as accounts, billing, dashboards, reports, API usage, permissions, integrations, incidents, troubleshooting, and data exports.

## Legal Source

The documents are project-owned synthetic documents created locally for this learning project. They are not copied from proprietary product docs or scraped websites.

## Target Scale

The dossier input target is about 1,100 documents and about 9,600 chunks.

These are targets, not measured results. If the real generated corpus has a different number of documents or chunks, I will record the measured count instead of changing the number to match the target.

## Raw Document Format

Raw documents will be stored as Markdown files under `datasets/corpus/raw/`.

Each document should have a stable document ID, a title, a category, and body text.

## Measured Counts

Measured after running:

```powershell
python scripts\generate_synthetic_corpus.py
python scripts\chunk_corpus.py

Results:
raw documents: 1,100
chunks: 9,900
chunk size: 650 characters
chunk overlap: 100 characters