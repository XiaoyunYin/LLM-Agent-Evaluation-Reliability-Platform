# P4a Deterministic Matrix

P4a validates the Python-native durability protocol without model calls. It
replays the frozen P3 reference trajectories, injects each supported crash window
at every effectful step, recovers after lease expiry, and verifies the final
SQLite world with the P3 verifier.

This is not a new P3 baseline and does not change frozen P3 artifacts.

## Run

Command:

```powershell
$env:PYTHONPATH='.'; python -m scripts.run_p4a_matrix --run-id p4a_matrix_20260813
```

The raw matrix output is generated locally and is not committed to the public
repository. The result table below is the retained public summary.

Freeze tag:

`p4a-frozen`

The audit output is also generated locally by the same command.

## Result

| Measure | Value |
|---|---:|
| model calls | 0 |
| total cases | 915 |
| clean cases | 80 |
| crash cases | 835 |
| passed cases | 915 / 915 |
| quarantine written | no |

Acceptance counters were all zero:

| Counter | Value |
|---|---:|
| duplicate_side_effects | 0 |
| lost_required_effects | 0 |
| incorrect_final_states | 0 |
| stale_fenced_effects_accepted | 0 |
| orphan_effect_records | 0 |
| invariant_violations | 0 |

The audit reconstructs expected rows from the frozen 80-task suite and verifies
that every expected `(task_id, crash_window, step_index, tool_name)` combination
appears exactly once:

| Crash window | Cases |
|---|---:|
| clean | 80 |
| before_intent_insert | 167 |
| after_intent_before_effect | 167 |
| inside_before_effect_application | 167 |
| after_effect_before_step_completion | 167 |
| after_step_before_next_model | 167 |

Tool/window coverage:

| Tool | Cases per crash window |
|---|---:|
| update_ticket | 80 |
| assign_ticket | 77 |
| add_comment | 10 |

The audit also verifies zero values row-by-row for each promised acceptance
counter and each protocol invariant:

- durable_intent_duplicates
- effect_result_duplicates
- effects_without_intent
- completed_without_result
- stale_fenced_effects_accepted
- duplicate_business_mutations

## Supplemental Recovery

The 915-case matrix does not include stale-worker fencing or poison/DLQ rows.
Those scenarios are outside the supported public claim.

| Scenario | Result |
|---|---:|
| double-crash recovery | 1 / 1 |
| stale-worker fencing simulation | 1 / 1 |
| poison-to-DLQ | 1 / 1 |

## Scope

This run covers the current P4a deterministic protocol surface:

- runner state persistence
- immutable model decisions
- intent-before-effect durability
- idempotent effect result recording
- lease-expiry recovery
- quarantine tombstone generation on failed reports

The supplemental recovery run covers:

- double-crash recovery
- stale-worker fencing-token rejection
- poison-to-DLQ after three failed attempts with zero effects

The stale-worker case is a protocol-level fencing simulation, not an OS SIGSTOP
test.

P4b integration with the distributed Java substrate remains out of scope for
this run.

## Verification Notes

The matrix artifact SHA-256 was recomputed from disk after documentation updates:

`9F60CE9E933EDBECBA5CE35199A8CCFED3336D2F44769FADF2C4FB585E6D4FD4`

During one shell run, the default `python` interpreter was
`D:\anaconda3\python.exe` and could not execute canonical
`scripts.assert_p3_frozen` because `langchain_core` was unavailable there. A
read-only manifest verification in that environment confirmed fixture hash
`18d64bd9595c`, suite hash `2cfcaedbb400`, and 80 frozen tasks. The canonical
assertion succeeded under the project virtualenv:

```powershell
.\.venv\Scripts\python.exe -m scripts.assert_p3_frozen
```

Result:

`frozen benchmark intact: 80 tasks, suite 2cfcaedbb400, budget 20`
