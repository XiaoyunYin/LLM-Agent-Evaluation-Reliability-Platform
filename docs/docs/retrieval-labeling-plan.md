# Retrieval Held-Out Labeling Plan

## Purpose

This file defines the labeling protocol for the held-out retrieval evaluation set.

The dataset target is 120 labeled queries. Each query is paired with one or more stable relevant chunk IDs from `datasets/corpus/chunks.jsonl`.

## Held-Out Definition

This is a held-out query set, not a classic document train/test split.

The corpus stays fixed. The held-out part is the query set and its relevance labels. Retrieval settings should not be tuned on this final 120-query set.

## Label Timing and Blindness

Relevance labels must be created before looking at GPT-4o-mini judge outputs, 7B judge outputs, generated answers, or retrieval benchmark scores.

Labels are judgments about which chunks are relevant to the query, independent of whether a model later answers correctly.

## Query Format

Each query record should include:

- query ID
- query text
- held-out split marker
- category metadata
- relevant chunk IDs
- graded relevance labels
- labeling notes or limitations

Each JSONL record should use this shape:

```json
{
  "id": "RH-001",
  "query": "Natural-language retrieval query",
  "split": "heldout",
  "labeling_protocol_version": "retrieval_labels_v0.1",
  "labels_created_blind_to_judge_outputs": true,
  "categories": {
    "difficulty": "easy",
    "hop_type": "single-hop",
    "match_type": "semantic/paraphrase",
    "domain": "accounts"
  },
  "relevant_chunks": [
    {
      "chunk_id": "doc_support_accounts_0001_chunk_0001",
      "relevance": 2,
      "note": "Short reason this chunk is relevant."
    }
  ],
  "labeling_limitations": [
    "single_annotator",
    "synthetic_corpus",
    "not_exhaustively_judged_against_every_chunk"
  ]
}
```

Field meanings:

- `id`: stable query ID.
- `query`: natural-language information need.
- `split`: must be `heldout`.
- `labeling_protocol_version`: version of the labeling method.
- `labels_created_blind_to_judge_outputs`: must be `true` for this held-out set.
- `categories`: stratification metadata for slice-based retrieval analysis.
- `relevant_chunks`: stable chunk IDs with graded relevance labels.
- `labeling_limitations`: known limits of the labeling process.

## Relevance Scale

Use graded relevance labels:

- `0`: not relevant
- `1`: partially relevant
- `2`: highly relevant

A label of `2` means the chunk directly supports answering the query. A label of `1` means the chunk is related or useful but incomplete.

## Query Category Distribution

The 120-query set is stratified across:

- easy
- hard
- single-hop
- multi-hop
- exact-term
- semantic/paraphrase

Target distribution:

| difficulty | hop_type | match_type | count |
|---|---|---|---:|
| easy | single-hop | exact-term | 15 |
| easy | single-hop | semantic/paraphrase | 15 |
| easy | multi-hop | exact-term | 15 |
| easy | multi-hop | semantic/paraphrase | 15 |
| hard | single-hop | exact-term | 15 |
| hard | single-hop | semantic/paraphrase | 15 |
| hard | multi-hop | exact-term | 15 |
| hard | multi-hop | semantic/paraphrase | 15 |

Total: 120 queries.

## Batch Labeling Plan

The final target is 120 held-out queries.

The set has 8 category cells:

- easy / single-hop / exact-term
- easy / single-hop / semantic/paraphrase
- easy / multi-hop / exact-term
- easy / multi-hop / semantic/paraphrase
- hard / single-hop / exact-term
- hard / single-hop / semantic/paraphrase
- hard / multi-hop / exact-term
- hard / multi-hop / semantic/paraphrase

Each cell contains 15 queries.

To reduce category imbalance, labeling should proceed in rounds. Each round adds one query to each category cell. After 15 rounds, the dataset contains 120 queries.

## Stable Chunk IDs

Relevant chunks must reference stable chunk IDs from `datasets/corpus/chunks.jsonl`.

Example:

```json
{
  "chunk_id": "doc_support_accounts_0001_chunk_0001",
  "relevance": 2
}
```

## Manual Labeling Workflow

For each query:

1. Write the query text before running retrieval benchmarks or judge scoring.
2. Assign the query categories: difficulty, hop type, match type, and domain.
3. Search the corpus chunks for candidate evidence.
4. Read the candidate chunks directly.
5. Assign graded relevance labels.
6. Record stable `chunk_id` values from `datasets/corpus/chunks.jsonl`.
7. Add a short note explaining why each positive chunk is relevant.
8. Do not inspect generated answers, GPT-4o-mini judge outputs, 7B judge outputs, or retrieval benchmark scores during labeling.

## Labeling Limitations

These labels have limitations:

- single annotator
- synthetic corpus
- assistant-generated initial labels that need human review before public claims
- not guaranteed to identify every relevant chunk
- synthetic template repetition creates near-duplicate relevant chunks
- graded relevance involves judgment
- labels may need versioning if the corpus changes

Because the corpus is templated, another chunk may contain very similar evidence. This limitation should be considered when interpreting retrieval metrics.

## Anti-Leakage Rules

Do not change labels to make retrieval metrics look better.

Do not inspect model-generated answers before labeling.

Do not inspect GPT-4o-mini or 7B judge outputs before labeling.

If labels are corrected later, record the reason and create a new label version.

## Validation

During drafting, run:

```powershell
python scripts\validate_retrieval_labels.py
```

This validates structure, required fields, category values, relevance values, duplicate query IDs, duplicate query text, and chunk ID existence.

For the full held-out set, run:

```powershell
python scripts\validate_retrieval_labels.py --strict
```

Strict mode additionally enforces exactly 120 records and exactly 15 records in each category cell.
