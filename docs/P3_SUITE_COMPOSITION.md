
# P3 Suite Composition — Pre-Committed Before Generation

Written **before** the additional tasks exist. Composition is fixed by structure,
not by outcome: a candidate is included because it satisfies a declared structural
quota, never because of whether the agent passes it.

---

## 1. The one-time rebalancing pass, amended

The original rule permitted one difficulty/fairness pass to remove ambiguous,
impossible, or duplicate tasks. That pass was never spent, and the situation it
was written for did not occur. What occurred instead:

**The 33-task suite saturated once the substrate defects were fixed.** Calibration
success went 24.2% → 66.7% → ~96%, and every edit removed a benchmark defect —
tasks that were impossible or ambiguous given the tool surface. Nothing was made
easier. The ceiling is a property of the composition: the families are
structurally shallow, and once the tools could express them the agent solved them.

**Amended definition.** The single permitted pass is a **composition/difficulty
expansion pass**, with:

| | |
|---|---|
| **Trigger** | Measured ceiling after substrate defects were removed (~96% on the calibrated core) |
| **Scope** | Add new, structurally harder task **families**. |
| **Explicitly out of scope** | Modifying an individual task because the agent passes it. Making the existing core artificially harder. Removing a task for being easy. |

The 33 calibrated tasks are **preserved unchanged** as the core tier — an
easy/medium regression anchor. Their calibration history (contract v0 → v1, all
defect fixes, per-round results) stays in
`docs/P3_CALIBRATION_CHANGELOG.md`.

After this pass, difficulty tuning ends.

---

## 1b. Outcome of the pass — it did not create difficulty

Recorded here because §1 pre-committed the pass and honesty requires the result
next to the intent.

The pass added five families. Their first calibration read **49.2%**, which looked
like restored discrimination. It was not: three benchmark defects were suppressing
it (calibration-changelog edits 9–11), chiefly a fixture where **no ticket was
uniquely identifiable by customer and issue**, so tasks naming a ticket that way
had two or three equally correct answers.

After the fixes, on the same commit and model:

| Tier | Defective | Fixed |
|---|---:|---:|
| core | 97.0% | **98.0%** |
| hard | 49.2% | **96.2%** |

**The suite is saturated for this model, and the single permitted pass is spent.**
Task-level success is reported as a non-discriminating metric rather than tuned
until it discriminates. Manufacturing harder tasks now would be fitting the
benchmark to a desired number, which §1 explicitly forbids.

The tier split below still stands and still has a use — core as regression canary
— but the **primary P3 discrimination signal moves to call-level behaviour**,
where the pre-registered intervention thresholds are met (§9b).

---

## 2. Tier interpretation, pre-declared

The blended 80-task aggregate is **not** the headline. Declared before any
baseline so the framing cannot be chosen after seeing numbers:

| Tier | Role |
|---|---|
| **Core** (the calibrated 33) | Regression canary / substrate sanity. Expected to stay high. A large drop here means the substrate or agent regressed, not that the benchmark got harder. |
| **Hard** (new families) | **Primary discrimination metric.** |
| **Family-level results** | Primary diagnostic lens. |
| **Pooled 80-task success** | Secondary combined summary only. |

---

## 3. Pre-committed quotas

Target ~80 tasks. **No family exceeds 20%** (16 tasks).

| Tier | Family | Target | Provenance |
|---|---|---:|---|
| core | `simple_update` | 8 | calibrated-core |
| core | `lookup_update` | 8 | calibrated-core |
| core | `policy_update` | 4 | calibrated-core |
| core | `multi_field` | 4 | calibrated-core |
| core | `multi_ticket` | 3 | calibrated-core |
| core | `conditional_escalation` | 6 | calibrated-core |
| **hard** | `chained_resolution` | 10 | hard-calibration-derived / fresh |
| **hard** | `policy_selection` | 10 | hard-calibration-derived / fresh |
| **hard** | `distractor_resolution` | 10 | hard-calibration-derived / fresh |
| **hard** | `multi_ticket_conditional` | 9 | hard-calibration-derived / fresh |
| **hard** | `noop_plus_mutation` | 8 | hard-calibration-derived / fresh |
| | **Total** | **80** | |

Every task records `provenance` ∈ `calibrated-core`, `hard-calibration-derived`,
`fresh-generated`, so the selection-bias check in §7 can run.

---

## 4. Structural difficulty attributes

Recorded on every task, and the basis for inclusion:

| Attribute | Meaning |
|---|---|
| `reference_call_count` | tool calls in the reference solution |
| `entities_involved` | distinct entities that must be resolved |
| `required_mutations` | count of required state changes |
| `retrieval_required` | must consult the policy corpus |
| `cross_entity_resolution` | must resolve name → id across entities |
| `distractor_count` | plausible-but-wrong candidates present |
| `conditional_branches` | branch points on fixture state |
| `tickets_affected` | tickets that must change |
| `policy_reasoning_required` | must select among competing policies |
| `requires_noop_decision` | must correctly decide *not* to change something |

### Required structural attributes per hard family

| Family | Must have |
|---|---|
| `chained_resolution` | `cross_entity_resolution` ≥ 2, `entities_involved` ≥ 3 |
| `policy_selection` | `policy_reasoning_required`, ≥ 3 candidate policies, exactly 1 applicable |
| `distractor_resolution` | `distractor_count` ≥ 3 |
| `multi_ticket_conditional` | `tickets_affected` ≥ 3, `conditional_branches` ≥ 1 |
| `noop_plus_mutation` | `requires_noop_decision`, plus ≥ 1 required mutation elsewhere |

---

## 5. Policy applicability must be machine-decidable

Prose interpretation is not an applicability test. Every policy carries structured
metadata:

```json
{"applies_to": {"tier": ["enterprise"], "topic": "technical",
                "signal": "outage"},
 "actions": [{"field": "escalated", "value": 1}, ...]}
```

For an intended single-policy task, **exactly one** policy must satisfy the
applicability predicate against the task's attributes. That is asserted in QA, so
a task with two applicable policies is a defect caught before the agent sees it —
not an ambiguity discovered from a confusing failure.

---

## 6. Conditional verification must be independent of generation

Where required actions depend on fixture state, the verifier and QA **recompute
the condition from the fixture**, never from a generator-produced
`expected_branch` field.

If the generator and the checker read the same precomputed value, a generator bug
is invisible — the same failure mode as a generator and its own check sharing an
assumption, which already produced the no-op-required-change defect earlier in
calibration.

---

## 7. Provenance-selection-bias check, pre-declared

After baselines, compare pooled success of `calibrated-core` /
`hard-calibration-derived` tasks against `fresh-generated` tasks **within
comparable families and difficulty attributes**.

If calibrated tasks are systematically easier, that is selection bias introduced
by editing, and it is reported before any pooled result is presented as
representative.

---

## 8. Model-turn budget — deliberately NOT frozen

The current 10-turn cap is **calibration-only**. Harder families legitimately need
longer trajectories, and freezing a budget derived from shallow families would
make valid hard tasks budget-impossible.

Final budget is derived once all ~80 reference trajectories exist:

- record median, p95, maximum reference length, and per-family maxima
- apply the pre-committed multiplier **≈2.5× the longest legitimate reference
  requirement**, adjusting only if the calls→model-turns mapping requires it
- document the exact derivation

**The binding requirement: no valid task may be budget-impossible.**

---

## 9. Frozen failure taxonomy — defined before baselines

Categories are fixed now so frequencies cannot reshape the definitions:

| Category | Meaning |
|---|---|
| `malformed_typed_call` | arguments fail schema/enum validation |
| `valid_schema_wrong_arguments` | schema-valid, semantically wrong (wrong value) |
| `wrong_entity` | right action, wrong ticket/customer/team |
| `wrong_tool` | a different tool was needed |
| `policy_selection_failure` | applied an inapplicable policy, or missed the applicable one |
| `retrieval_failure` | did not consult the policy corpus when required |
| `incomplete_workflow` | some required mutations made, others missing |
| `wrong_mutation` | a required field set to the wrong value |
| `undeclared_mutation` | a change outside required ∪ allowed |
| `termination_failure` | stopped without finishing, or hit the turn cap |
| `correct_actions_verifier_mismatch` | actions look right but the verifier disagrees — always investigated as a possible verifier defect |

---

## 9b. Selected intervention — decided by the pre-registered rule

The rule was fixed before these numbers existed: schema repair is selected if
invalid typed calls are ≥2% of relevant calls, **or** ≥15% of episodes contain
one. Measured over 3 repeats × 60 tasks:

| Signal | Measured | Threshold | Clears |
|---|---:|---|:--:|
| invalid typed calls | 49/930 = **5.27%** | ≥2% | yes |
| episodes with ≥1 invalid call | 49/180 = **27.2%** | ≥15% | yes |

**Schema repair is selected.** Because task success is saturated, its primary
outcome metrics are call-level (invalid-call rate) and efficiency (turns, tokens,
cost per solved task), not task success — where there is no headroom to move.

---

## 10. Contract status

Contract **v1** is the starting point, not the frozen contract. During hard-family
calibration it may change only for a documented **tool/runtime defect** or a
**genuine missing capability needed to make a valid task solvable**. Every change
enters the calibration changelog.

After the freeze, any agent-visible change is intervention-grade and requires a
bridge run.
