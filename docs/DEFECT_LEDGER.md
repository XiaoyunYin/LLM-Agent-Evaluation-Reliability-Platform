
# Substrate Defect Ledger

Every defect in this project that **silently corrupted measurement** — the harness
produced a plausible wrong number, or made a task unsolvable as written, and
**aggregate accuracy could not surface it**. Each was found by trajectory-level or
structural analysis.

Note the precision: *aggregate accuracy*, not *any* aggregate. Defect 3
(`RATE_LIMITED` treated as completed) was count-catchable and was in fact caught by
an integrity count, as was its cousin the 2,042-row contaminated run. What none of
the 11 would have shown up in is the accuracy number itself.

This ledger provides the itemized record behind the defect count.

**Scope.** Included: defects in the evaluation substrate (tools, fixtures, task
specs, resume/termination logic, the vendored evaluator) whose effect was a wrong
or unattainable measurement. Excluded: ordinary bugs caught by tests before they
influenced a number, and reporting errors caught by the claims audit — those are
tracked separately in `docs/claims.md` and counted in their own claim.

---

## The ledger

| # | Phase | Class | Defect | How it presented | Detected by |
|---|---|---|---|---|---|
| 1 | P0 | tool contract | `inspect_schema` accepted an unrecognised argument (`table` vs `table_name`) and returned the **table list** — a valid-looking answer to a question never asked | agent re-requested the same description until its step budget expired; cost 3/10 smoke episodes | step-level trajectory reading |
| 2 | P0 | evaluator | the vendored evaluator's timeout wrapped a blocking `cursor.execute` in `asyncio.wait_for`, which cannot cancel it | pathological queries would hang the scorer rather than time out | reading the vendored code while building `interruptible_eval.py`; 120/120 verdict parity afterwards |
| 3 | P0 | resume logic | resume treated `RATE_LIMITED` episodes as completed | a resumed run would have silently scored a **smaller benchmark** and reported it as a full run | auditing `completed_task_ids()` against termination reasons |
| 4 | P3 | tool contract | `search_tickets(customer_id=<a name>)` returned `SUCCESS_EMPTY` instead of rejecting | `lookup_update` scored 0/24; the agent behaved *correctly* on a false premise | family success being bimodal (24/24 vs 0/N) |
| 5 | P3 | capability gap | team ids were opaque and no tool exposed them | `policy_update` scored 0/12; the agent guessed, was correctly refused, then had no route to the answer | same bimodal family signature |
| 6 | P3 | fixture | 20 customers × 10 subjects shared a cycle, so a customer's subject was a *function* of the customer — **zero of 60 tickets were uniquely identifiable** by customer and issue | "find their lockout ticket" had three correct answers; **two** families unsolvable as written (see trace below) | 10 hard tasks failing 3/3, then trajectory inspection |
| 7 | P3 | task spec | `noop_plus_mutation` required only the team assignment while the cited policy also mandates normal priority | an agent applying the policy **exactly** was failed for an undeclared mutation | deterministic same-signature failure across repeats |
| 8 | P3 | tool contract | `query` matched by substring, `customer_name` matched exactly, neither documented | a partial name returned `SUCCESS_EMPTY`, which the adopted `accept_empty` policy correctly tells the agent to act on — a silent dead end | trajectory: the same agent used the full name correctly on a sibling task |
| 9 | P3 | fixture | two subjects shared the `shipping_delay` signal, re-creating ambiguity that an existing uniqueness check was "guarding" | `SUP-distract-001/003` failed 10/10 on an equally-valid ticket | baseline taxonomy: identical `wrong_entity` signature across all repeats |
| 10 | P3 | task spec | `multi_ticket_conditional` said "change nothing else" while citing policies that mandate escalation and team assignment | the agent applied the policy correctly and was failed for an undeclared mutation | 4 tasks failing 10/10 with one signature |
| 11 | P3 | task spec | the prompt selected at **topic** grain ("shipping delays") where uniqueness only holds at **signal** grain | target not uniquely identifiable; 2 tasks failed 10/10 | third recurrence of the same signature |

**Total: 11.**

---

## Reconciliation — how 11 was reached, and what it is not

The count moved from a drafted "seven" to 11. Because "11" will be probed the way
"seven" was, the arithmetic is written down rather than asserted.

| | Count |
|---|---:|
| drafted figure (P0 `inspect_schema` + the six P3 calibration defects) | 7 |
| + P0 substrate defects the draft omitted (#2 evaluator timeout, #3 `RATE_LIMITED` resume) | +2 |
| + P3 tool-contract defects predating the calibration table (#4 `customer_id`-as-name, #5 undiscoverable team ids) | +2 |
| **total** | **11** |

**Nothing was evicted.** An earlier commit message for this file said three P0
defects had been omitted; that was wrong — it counted `inspect_schema` as an
addition when it was already inside the drafted seven. The ledger itself was
correct; the commit message's arithmetic was not. Corrected here rather than
silently.

### What this count deliberately excludes

Reporting errors caught by the claims audit are **not** in this ledger, because
they are counted in their own claim and the two numbers must not double-count the
same finding. Those were: the span-reconciliation check that silently skipped 19%
of tool steps, the span count truncated at Elasticsearch's 10,000 default, the
non-re-derivable cost figure, and the "49 flips" miscount that was actually
termination-reason churn.

The distinction is the effect, not the severity. A ledger defect corrupted **what
the harness measured**; an audit defect corrupted **what was reported about a
correct measurement**.

Also excluded: ordinary bugs caught by tests before they influenced any number
(for example `--no-resume` leaving duplicate episodes, fixed before a published
run used it).

---

## Trace for defect 6 — why "two families", not one

The claim moved from "an entire family" to "two task families" between drafts, so
the evidence is recorded. The 20×10 cycle was fixture-wide, not family-local: it
made **every** (customer, subject) pair non-unique across all 60 tickets, so any
family whose prompt identified a ticket by customer plus issue was affected. Two
families did:

| Family | Tasks failing 3/3 on the defective fixture | Failure signature |
|---|---|---|
| `chained_resolution` | `SUP-chain-002` (and `SUP-chain-001` intermittently, 1/3) | acted on the customer's *other* lockout ticket |
| `distractor_resolution` | `SUP-distract-001`, `-002`, `-003`, `-009` | acted on the customer's *other* shipping ticket |

The remaining three hard families (`noop_plus_mutation`, `policy_selection`,
`multi_ticket_conditional`) identify their targets by explicit ticket id and were
untouched by this defect. `noop_plus_mutation`'s failures in the same run trace to
defect 7, which is a separate entry.

So: fixture-wide cause, two families affected. "An entire family" understated it.

---

## What the ledger shows

**Three recurrences of one pattern.** Defects 6, 9 and 11 are all ambiguous task
targets, and in the last two a uniqueness assertion **already existed and passed**
— because the check and the prompt derived their key independently (subject vs
signal vs topic). The fix that finally held was to stop inferring the key: tasks
carry `selector_signal` and `selector_customer` as explicit fields, the prompt is
built from them, and QA asserts that pair names exactly one row. Check and prompt
now cannot disagree, because they read the same value.

**Four instances of silent tool failure.** Defects 1, 4, 5 and 8 share a shape: a
tool accepts input it should reject and returns something indistinguishable from a
real answer. Full analysis in `docs/SILENT_TOOL_FAILURE.md`. The rule that came out
of it: a valid request matching nothing is `SUCCESS_EMPTY`; a malformed request is
a structured error; the two must never share a representation.

**Not one was visible in the accuracy number.** Every detection came from either
step-level trajectories or a structural breakdown (per-family success showing an
implausible cliff, or a task failing every repeat with an identical signature).

**Defects per P3 iteration: 3 → 2 → 1.** The rate fell as the QA checks
accumulated, which is the only evidence available that the class was being closed
rather than merely sampled.
