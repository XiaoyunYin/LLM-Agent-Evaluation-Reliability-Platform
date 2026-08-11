# Judge Rubric

The judge returns the shared JSON schema used by GPT-4o-mini and the
self-hosted 7B judge:

- `correctness`
- `faithfulness`
- `citation_quality`
- `passed`
- `explanation`

This file exists so judge rubric changes are visible to the CI regression gate.
The active rubric is still implemented in `backend/app/gpt4o_mini_judge.py`.
