
# P3 — Frozen Results

Stateful agentic evaluation: an 80-task support-ticket benchmark with declarative
state verification, a frozen tool contract, and one pre-registered intervention
run to a verdict.

**Frozen artifact:** `config/p3_frozen_manifest.json`
**Suite hash:** `2cfcaedbb400…`  ·  **80 tasks**  ·  **budget 20 model turns**
**Model:** `gpt-4o-mini`  ·  **Verified by:** `scripts/assert_p3_frozen.py` before every paid run

Final task IDs, full family denominators, intervention arm sizes, and the
post-P3 intervention-selection doctrine are pinned in
[`docs/P3_CLOSING_FACTS.md`](../P3_CLOSING_FACTS.md).

---

## 1. What is measured

Not "did the model produce good-looking text". Every task declares the state
change it requires, and the verifier compares the normalized before/after diff of
a real SQLite world:

```
required ⊆ actual ⊆ required ∪ allowed        actual ∩ forbidden = ∅
```

Any undeclared mutation fails. No LLM judges correctness — comment checks are
structured predicates. A judge that can be argued into a pass is not a verifier.

## 2. Substrate quality, established before any agent ran

| | |
|---|---:|
| verifier QA checks (known-good **and** known-bad) | **452 / 452** |
| reference solutions replayed through the real runtime | **80 / 80**, zero model calls |
| longest legitimate reference | 7 tool calls |

QA includes adversarial cases by design: a verifier hardcoded to PASS scores 100%
on references alone, so partial-completion, wrong-value, unrelated-mutation and
forbidden-mutation cases carry the weight.

## 3. Frozen baseline — 10 repeats, 800 episodes

| Metric | Value |
|---|---:|
| **global task success** | **90.25%** (sd 1.75%, range 88.75–93.75) |
| core tier (35 tasks) — regression canary | **97.7%** |
| **hard tier (45 tasks) — primary discrimination** | **84.4%** |

Tier roles were declared before any baseline ran, so the framing could not be
chosen after seeing which number flattered the result.

### By family

| Tier | Family | Success |
|---|---|---:|
| hard | `multi_ticket_conditional` | **22.5%** |
| core | `conditional_escalation` | 86.7% |
| hard | `distractor_resolution` | 91.1% |
| both | all seven other families | 100% |

### Consistency over 10 repeats

68 tasks always pass · 5 never pass · 7 intermittent.

## 4. The failures are real, and were read rather than assumed

A task failing every repeat is the signature of a **broken task**, not a hard one
— it meant exactly that six times during P3 calibration. So all five deterministic
failures were inspected at trajectory level before being accepted:

| Tasks | Behaviour | Verdict |
|---|---|---|
| `mtcond-001/002/003/004` | applies the **priority** half of each policy, never the **team** half | genuine — the policy states both, and the same agent assigns teams correctly in other families |
| `mtcond-007` | escalates a pro-tier outage that POL-011 explicitly excludes | genuine — over-applies the enterprise rule |

**Partial policy application under multi-entity load** is the headline capability
finding. An aggregate score reads 90% and says nothing about it.

### Frozen failure taxonomy (78 failures, categories fixed before baselines)

| Category | Share |
|---|---:|
| `incomplete_workflow` | 56.4% |
| `undeclared_mutation` | 23.1% |
| `forbidden_mutation_made` | 10.3% |
| `wrong_entity` | 10.3% |

## 5. Call-level behaviour

| | |
|---|---:|
| tool calls | 4,545 |
| invalid typed calls | 235 = **5.2%** |
| episodes with ≥1 invalid call | **29.4%** |
| episodes with ≥2 invalid calls | **0** |
| invalid calls never recovered from | **0 / 235** |

## 6. The pre-registered intervention, run to a verdict

Selection was decided by a rule fixed before the numbers existed (≥2% of calls or
≥15% of episodes). Both cleared, so **schema repair** was selected. Treatment: one
config flag adding the tool's JSON schema and a valid example to an
`INVALID_ARGUMENTS` payload — additive only, never coercing arguments, because
silently fixing a malformed call is the defect class this project keeps finding.

| Arm | Runs | Cohort success | Primary (repeat-invalid) |
|---|---:|---:|---:|
| baseline OFF | 10 | 96.0% | 0.0000 |
| bridge OFF (treatment commit) | 1 | 96.0% | 0.0000 |
| treatment ON | 4 | 93.0% | 0.0000 |

Cohort: 25 tasks provoking an invalid call in ≥3 of 10 baselines, frozen to
`config/p3_repair_cohort.json` before any treatment run. Above the pre-registered
floor of 8, so not underpowered.

**Bridge: ACCEPTED** — 92.50% global, inside the baseline range.

> ### Verdict: NO EFFECT
>
> The primary metric is **degenerate in both arms**. Zero episodes ever emitted a
> second invalid call, with or without the treatment.

Global success 90.25% → 90.31%: unchanged.

### Why that is the interesting result

The selection rule triggered on the **frequency** of invalid calls. What actually
matters is the frequency of invalid calls the agent **cannot recover from**, and
that is 0 of 235. Every invalid call was the same semantic slip — a customer name
passed into `customer_id` — and the existing error message already names the fix,
so the agent corrected on the very next turn every single time.

**A structured, actionable validation error was already sufficient for one-shot
recovery in 100% of observed cases.** Adding the schema on top had nothing left to
fix. The rule was not rewritten afterwards to change the verdict; it fired, that
is recorded as it happened, and the correction is logged as a lesson for the next
pre-registration.

Secondary metrics were measured and reported but **not promoted** — promoting a
secondary after the primary comes back null is how a null gets dressed up as a
finding.

## 7. Benchmark defects found and fixed during P3

Six, every one caught by repeats plus trajectory reading rather than by an
aggregate score:

| # | Class | Defect |
|---|---|---|
| 1 | fixture | 20 customers × 10 subjects shared a cycle — **zero** tickets uniquely identifiable by customer and issue |
| 2 | task/spec | required changes omitted what the cited policy mandates; an agent following the policy exactly was failed |
| 3 | tool/runtime | `query` substring vs `customer_name` exact — a partial name became a silent dead end |
| 4 | fixture | two subjects shared one signal, re-creating ambiguity a check was already "guarding" |
| 5 | task/spec | prompt said "change nothing else" while citing a policy mandating more |
| 6 | task/spec | prompt selected at **topic** grain where uniqueness only holds at **signal** grain |

Defects per iteration: **3 → 2 → 1**.

Three of the six were ambiguous targets where a uniqueness check existed *and
passed*, keyed one column away from the one the prompt used. The fix that held was
to stop inferring the key: tasks carry `selector_signal` and `selector_customer`,
the prompt is built from them, and QA asserts that pair names exactly one row.
Check and prompt now cannot disagree, because they read the same value.

## 8. Reproducibility

| | |
|---|---|
| P3 episodes executed | 3,439 across 51 runs |
| total API cost | $2.55 |
| superseded runs | quarantined with tombstones, never deleted |
| pinned by hash | fixture, task suite, tool schema, verifier, normalization, agent, prompt, budget |

Every superseded run keeps its data and carries a tombstone naming the run, the
contamination reason, the detection mechanism, and the superseded and current
suite hashes.

---

## What this does and does not claim

**Does:** an 80-task stateful agentic benchmark with execution-verified state
diffs, 452 adversarial verifier QA checks, a content-hash freeze, 10-repeat
baselines with measured variance, a pre-registered intervention run to a null
verdict, and six benchmark defects caught by trajectory-level analysis.

**Does not:** claim the intervention worked. It did not. It also does not claim
this benchmark discriminates between strong models — it was measured against one
model, `gpt-4o-mini`, and seven of eleven families are saturated at 100%.
