# Locked Inputs — Spider SQL Agent Benchmark (P0)

This configuration was frozen **before** the first agent run. Changing any value
invalidates comparisons with the recorded runs.

## Dataset pin

- Benchmark: `spider-1.0`
- Archive sha256: `5ddff97bb1d421282c593e8d30ce0ce107270f4dd4a21d60eba4bf287d5956b1`
- Archive bytes: 99,736,136
- Dev examples: 1,034
- Databases: 166
- `dev.json` sha256: `30d64a3fccde493226df79687aed9e4a1c0129525baf44f29c0573d914d758a4`
- `tables.json` sha256: `61bb20aa401f03164e2d7f3b16509b7b5f79cc9c943ca7bd159046df1159e2ed`
- Pinned at: 2026-08-13T00:42:43.992186+00:00

## Evaluator pin

- Evaluator: `spider-test-suite-sql-eval` (vendored from https://raw.githubusercontent.com/taoyds/test-suite-sql-eval/master/)
- Metric: `single_database_execution_accuracy`
- Flags: `plug_value=False`, `keep_distinct=False` — the official
  execution-accuracy defaults (`evaluation.py --etype exec`).

Vendored file hashes:

- `evaluation.py`: `7401e4014a8955376a7919c06903a7f0ab403c99e89f94204cd8f4c8e32ae779`
- `exec_eval.py`: `29d034db28904490c28037537a14fbb0150b6e86cef0049076c0511d6b6b77f7`
- `parse.py`: `ef04211a6e1c1e142571157f5c1999613e3451084c044083b2de1977f1f622c5`
- `process_sql.py`: `927fc564f7a8e34f09f009a2f5564a83fdf95226440dde84c87871fd65fe55a1`

## Split discipline

- Reported split: `dev`
- Train and dev are never mixed in a reported benchmark.

## Verifier QA (frozen)

- Gold-pass QA run at: 2026-08-13T03:35:07.780764+00:00
- Gold queries checked: 1,034
- Gold queries passing: 1,034

### Known-bad (adversarial) QA

| | |
|---|---:|
| Mutations attempted | 166 |
| Detected as wrong (correctly rejected) | 136 |
| Leaked (wrongly passed) | 0 |
| Execution-result collisions (discarded) | 30 |
| Collision rate on attempted mutations | 0.1807 |

A **collision** is a mutation whose SQL text differs from gold but whose
rows are identical on the shipped database, so single-database execution
accuracy cannot tell them apart. Those are discarded rather than counted as
verifier leaks, and every one is recorded with its task ID and mutated query
in the QA artifact.

**The collision rate is a property of this mutation set, not of the agent.**
It is not an estimate that the same share of the agent's passes are false
positives - the agent's queries are not drawn from this distribution.

## Frozen exclusion list

**Empty.** Every gold query in the reported split passes the evaluator,
so no task is excluded. Task success is measured over the full split.

## Rules

1. Exclusions are frozen at the timestamp above and are never edited after
   agent results exist.
2. Tasks are never silently skipped. A task is either measured or listed here
   with a reason.
3. Re-running `scripts/qa_spider_evaluator.py` regenerates this file only when
   the dataset pin changes; a differing exclusion set on the same pin is a
   defect to investigate, not a result to adopt.
