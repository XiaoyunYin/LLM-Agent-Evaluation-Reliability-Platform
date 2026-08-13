# Test-Suite Substrate QA

The distilled Spider test suite scores a query against **every** database
instance for its schema, not just the one shipped copy. It is a strictly
tighter metric, and it is reported **beside** single-database execution
accuracy — never as a replacement, so the frozen P0 number stays
comparable to itself.

Generated: 2026-08-13T07:33:47.583716+00:00

## Substrate

| | |
|---|---:|
| Metric id | `test_suite_execution_accuracy` |
| Database instances | 695 |
| Instances per `db_id` (mean) | 34.8 |
| Evaluator flags | `plug_value=False`, `keep_distinct=False` |

`plug_value` stays False because this agent predicts its own literal
values; plugging gold values in would measure a different system.

## Gold-pass QA on this substrate

| | |
|---|---:|
| Gold queries checked | 1,034 |
| Passing on every instance | 1,034 |
| Failing (excluded from the test-suite metric only) | 0 |
| **Denominator for the test-suite metric** | **1,034** |

No exclusions: every gold query passes on every instance.

## Adversarial QA on this substrate

| | |
|---|---:|
| Mutations attempted | 166 |
| Detected as wrong | 136 |
| Leaked (wrongly passed) | 0 |
| Execution-result collisions | 30 |
| Collision rate | 0.1807 |

**The collision rate describes this mutation set, not the agent.** It is not
an estimate of the share of the agent's passes that are false positives.

## Reproduce

```powershell
python scripts/download_spider_test_suite.py
python scripts/qa_spider_evaluator.py --split dev --substrate test_suite
```
