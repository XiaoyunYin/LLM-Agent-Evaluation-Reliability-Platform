# Candidate Generation Status

Generated at: 2026-08-07T03:24:08.866480+00:00

## Execution State

Production candidate-generation artifacts exist on disk.

## Actual Counts

- Actual run count with candidate-answer artifacts: 9
- Actual completed run count: 9
- Actual candidate-answer count: 970
- Failed candidate-answer rows: 4

## Candidate Answers By Provider

- anthropic: 490
- openai: 480

## Failed Rows By Provider

- anthropic: 4 (Anthropic generation failed.)

## Integrity Notes

- These are candidate answers only, not judged answers.
- Do not claim 60+ runs unless actual completed run count is at least 60.
- Do not claim OpenAI/Anthropic API coverage unless both providers have real completed candidate-answer rows.
- Do not claim 8K+ judged answers from this file.
- Resume works by reading existing `*_candidate_answers.jsonl` files and skipping completed case IDs.
