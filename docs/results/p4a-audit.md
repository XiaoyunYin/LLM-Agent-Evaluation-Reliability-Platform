
# P4a Audit — Is the Résumé Claim Supported?

Independent audit of the P4a durability matrix against the six questions that gate
the crash-safety résumé bullet. Every number below was recomputed from the
artifacts at `HEAD`, not read from `p4a-matrix.md`.

**Verdict: five of six clean. One — pause-class evidence — is absent, and the
bullet is written to not depend on it.**

---

## 1. Tag and commit

| | |
|---|---|
| tag | `p4a-frozen` |
| commit | `07c1e9c` — *Freeze P4a durability matrix*, 2026-08-13 |
| code + artifacts in that commit | `backend/app/support/durability.py` (896 lines), `scripts/run_p4a_matrix.py`, `scripts/audit_p4a_matrix.py`, `scripts/run_p4a_supplemental.py`, `tests/test_p4_durability.py`, `tests/test_p4_matrix_runner.py`, all three JSON artifacts |
| commits after the freeze | one, `1ce4b95`, **documentation only** |

Artifact hashes recomputed from disk at `HEAD`, all matching the published values:

```
p4a_matrix.json        9F60CE9E933EDBECBA5CE35199A8CCFED3336D2F44769FADF2C4FB585E6D4FD4
p4a_matrix_audit.json  D98222EAD20A0611175D7FD0C1AF0057A7DD7D3FE53507C1EAC4EF9C009E917B
p4a_supplemental.json  EEAD82EB8C1C298268D1DDEE899F2FA6332AAAB5CA420A6CCC633BDFF18ADB30
```

**Clean.**

## 2. Matrix factorization

915 is not a bag of cases; it factors exactly:

```
167 effectful steps × 5 crash windows  =  835 crash cases
                     +  80 clean runs  =  915 total
```

| Dimension | Composition |
|---|---|
| tasks | 80 (the frozen P3 suite: 35 core, 45 hard) |
| effectful steps | 167 — `update_ticket` 80, `assign_ticket` 77, `add_comment` 10 |
| crash windows | `before_intent_insert`, `after_intent_before_effect`, `inside_before_effect_application`, `after_effect_before_step_completion`, `after_step_before_next_model` |
| per-window cases | 167 each — verified: 835 named-tool crash cases ÷ 5 = 167, and per-tool 400/385/50 ÷ 5 = 80/77/10 |

Every crash window is injected at **every** effectful step, not sampled. The audit
artifact independently reconstructs the expected
`(task_id, crash_window, step_index, tool_name)` set from the frozen suite and
confirms each combination appears exactly once.

**Clean.**

## 3. Is 915/915 the last clean full pass, under rerun-after-any-fix?

Yes, and verified rather than assumed. The matrix was re-run at `HEAD` during this
audit:

```
run_id p4a_verify_rerun
model calls 0
cases 915   clean/crash 80/835
passed 915/915
acceptance totals all zero
all_passed True
```

No code has changed since the freeze — the only subsequent commit is
documentation — so this is a reproduction, not a re-validation after a fix. The
stronger property (a fix landed, everything re-run) has not been exercised because
no fix has been needed since.

**Clean, with that scope stated.**

## 4. Pause-class results

**Absent.** This is the one gate that does not pass.

| Measure | Value |
|---|---:|
| stale-token attempts across all 915 matrix cases | **0** |
| stale-token attempts in the supplemental | **1** |
| stale attempts rejected | 1 (`stale_rejected: true`) |
| stale fenced effects accepted | 0 |

So a stale token *was* generated and *was* rejected — but exactly once, in a
**protocol-level simulation**, which `p4a-matrix.md` states plainly is *not* an OS
SIGSTOP test. The matrix itself never exercises fencing at all.

The distinction that matters to a distributed-systems interviewer: the mechanism
is implemented and one synthetic stale token was refused; no worker was ever
actually paused, expired, and resumed while holding a live handle. That is the
evidence a fencing claim needs, and it does not exist yet.

**Consequence: the word "fencing" stays off the résumé.** It returns when a
pause-class test — real `SIGSTOP`, lease expiry, resume, then the paused worker
attempting its write — reports stale-token rejections > 0. That is a small piece of
work and is the single highest-value next step for P4.

## 5. Trajectory-level resume

Demonstrated. Every one of the 915 cases records `completed_steps > 0`, meaning
each crashed episode was recovered after lease expiry and driven to completion
rather than restarted from zero. The supplemental adds the harder case:

| Scenario | Evidence |
|---|---|
| double-crash recovery | 2 crashes observed, 5 steps completed, 3 effect records, `runner_state: SUCCEEDED`, 0 duplicate business mutations |
| poison-to-DLQ | dead-lettered after three failed attempts with **zero** effects applied |

**Clean.**

## 6. Are final states checked by the snapshot-diff verifier?

Yes — this was the question most worth checking, because a durability harness that
grades itself on its own bookkeeping proves nothing about the world.

All 915 cases carry a full P3 `verify()` result — same verifier, same
normalization, same required/allowed/forbidden semantics as the frozen benchmark:

```
verifier_version       support_verifier_v1   (915/915)
normalization_version  support_normalize_v1  (915/915)
passed                 True                  (915/915)
```

So the claim is not "the ledger looks consistent" but "the resulting database is
the state the task required, after a crash at every effectful step."

**Clean.**

---

## Acceptance counters — all zero, across all 915

| Counter | Value |
|---|---:|
| `duplicate_side_effects` | 0 |
| `lost_required_effects` | 0 |
| `incorrect_final_states` | 0 |
| `stale_fenced_effects_accepted` | 0 |
| `orphan_effect_records` | 0 |
| `invariant_violations` | 0 |

Protocol invariants, verified row-by-row by the audit script:
`durable_intent_duplicates`, `effect_result_duplicates`, `effects_without_intent`,
`completed_without_result`, `stale_fenced_effects_accepted`,
`duplicate_business_mutations` — all zero.

---

## What the résumé bullet may therefore say

> Proved crash-safe execution for effectful agents — zero duplicate effects, zero
> lost effects, zero incorrect final states across 835 injected crashes plus 80
> controls (915/915), covering five crash windows at every mutating step, with
> write-ahead intents, idempotency keys and lease-based recovery, verified
> deterministically with no model calls.

Supported by items 1, 2, 3, 5 and 6. It deliberately does not say "fencing", does
not say "exactly-once", and does not claim a pause-class test.

## What it may not say, until the work exists

- **"fencing tokens"** — needs a pause-class test with stale-token rejections > 0
- **"exactly-once"** — the zeros are the stronger and unimpeachable claim
- **"survives worker failure in production"** — this is a deterministic harness on
  a single host with a simulated crash, not a distributed deployment. P4b
  integration with the Java substrate has not started.
