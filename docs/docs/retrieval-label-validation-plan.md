# Retrieval Label Validation Plan

## Purpose

This validator checks the held-out retrieval label file before benchmark code uses it.

It should catch simple mistakes early, such as invalid JSON, missing fields, invalid relevance values, wrong category names, duplicate query IDs, and chunk IDs that do not exist in the corpus.

## Inputs

Label file:

`datasets/labels/retrieval_heldout_120_v0.1.jsonl`

Corpus chunk file:

`datasets/corpus/chunks.jsonl`

## Checks

The validator should check:

- every line is valid JSON
- every record has an `id`
- every record has a non-empty `query`
- every record has `split` equal to `heldout`
- every record has `labels_created_blind_to_judge_outputs` equal to `true`
- every record has `categories`
- `difficulty` is either `easy` or `hard`
- `hop_type` is either `single-hop` or `multi-hop`
- `match_type` is either `exact-term` or `semantic/paraphrase`
- every record has at least one relevant chunk
- every `relevance` value is one of `0`, `1`, or `2`
- every relevant `chunk_id` exists in `datasets/corpus/chunks.jsonl`
- query IDs are unique

## Later Checks

When the set reaches 120 queries, the validator should also check:

- exactly 120 records
- exactly 15 records in each category cell
- no duplicate query text
- no label record depends on judge outputs