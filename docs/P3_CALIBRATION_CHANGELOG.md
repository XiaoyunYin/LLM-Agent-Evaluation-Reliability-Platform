# P3 Calibration Changelog

Every change to a calibration task, fixture, verifier, or tool contract, with its
category and rationale. Categories are fixed in `docs/P3_CONTRACT_V0.md` §5.

**Poor model performance alone is never a valid category.** A task the agent fails
for a real reason is a measurement. Editing it because the score disappoints turns
the benchmark into a description of what the model already does.

| # | Date | Category | Target | Change | Rationale |
|---|---|---|---|---|---|
| 1 | 2026-08-13 | task/spec defect | `simple_update`, `lookup_update`, `policy_update`, `multi_field`, `multi_ticket`, `conditional_escalation` | Filter out tickets whose current value already equals the target when generating required changes | Verifier QA found two reference sequences failing. Root cause was not the verifier: two account-lockout tickets were already at priority `high`, so the required change produced no diff and the tasks were **unpassable regardless of agent behaviour**. Task count 35 → 33. |
| 2 | 2026-08-13 | verifier defect | `qa_support_verifier.py` | Isolation probe now picks a value that genuinely differs from the fixture's current one | Same root cause as #1. The probe set `TKT-0001` to a priority it already had, measured zero changes, and reported a false isolation failure. |
| 3 | 2026-08-13 | tool/runtime defect | `support_tools_v0` | Empty-result labelling moved from per-call-site to a single `apply_empty_result_policy`, and `call_tool` became the one runtime entry point | Twenty call sites are twenty chances for one tool to drift out of the contract. Also added `UNKNOWN_TOOL` handling, which had no defined payload before. |

| 4 | 2026-08-13 | tool/runtime defect | `search_tickets` | Added a `customer_name` filter | Calibration round 1: `lookup_update` scored **0/24**. Tasks name the customer, but the only filter was `customer_id`, so there was no route from a name to a ticket. The agent passed the name into `customer_id`, got zero rows, and correctly reported no ticket found — behaving well against an impossible task. |
| 5 | 2026-08-13 | tool/runtime defect | new `list_reference_data` | Added a read tool listing valid team and agent ids | Same round: `policy_update` scored **0/12**. The agent tried `team_id="technical"` against a real id of `TEAM-technical`, then burned turns searching for an identifier it had no way to discover. Guessing an opaque id is not the capability under test. Contract v0 → v1. |
| 6 | 2026-08-13 | tool/runtime defect | `search_tickets` | An unknown `customer_id` is now refused with `INVALID_ARGUMENTS` naming `customer_name`, instead of returning zero rows | Round 2: `lookup_update` was still 3/24. The agent kept passing a name into `customer_id` and the tool answered with a plausible-looking empty result. This is the same silently-wrong-answer class as the P0 `inspect_schema` defect — a tool that accepts something wrong and responds plausibly is undetectable to its caller. |
| 7 | 2026-08-13 | coherent ambiguity | `POL-001`, `POL-007` | Policy text now names the mechanism: set the `escalated` **flag**, not `status`, and leave status unchanged | Round 2: `policy_update` was 0/12, missing `escalated` 11 times. The domain has **both** a status value `escalated` and a boolean field `escalated`, and the policy said only "escalated immediately". Either reading was defensible, so the ambiguity was in the benchmark, not the agent. |

### Measured effect of the calibration edits

| Round | Contract | Success | Notes |
|---|---|---:|---|
| 1 | v0 | **24.2%** (8/33, all three repeats) | `simple` 24/24, every other family 0/N |
| 2 | v1 (+`customer_name`, +`list_reference_data`) | **66.7%** | `MAX_STEPS` fell from 29 to 0 |
| 3 | v1 (+id validation, +policy wording) | **97.0 / 93.9 / 97.0%** | — |

No edit was made because a score was disappointing. Each traced to a task being
impossible or ambiguous given the tool surface, which is the documented category.

| 8 | 2026-08-13 | task/spec defect | `chained_resolution` | Filter no-op changes on **both** required fields, not just `team_id` | The independent QA no-op check caught `SUP-chain-002` requiring `priority=high` on a ticket already at high. Same class as edit #1, in a family written after that fix - which is why the check recomputes from the fixture instead of trusting the generator. |

| 9 | 2026-08-13 | **fixture defect** | whole fixture | Offset the subject index by the block number so each customer's three tickets are three different subjects | 20 customers and 10 subjects shared a cycle; 10 divides 20, so a customer's subject was a *function* of the customer. **Zero of 60 tickets had a unique (customer, subject) pair.** Every `chained_resolution` and `distractor_resolution` task had 2-3 equally correct answers, and `distractor_resolution` additionally forbade other tickets of the *target* customer - unpassable by reading. Found by 10 hard tasks failing 3/3. |
| 10 | 2026-08-13 | task/spec defect | `noop_plus_mutation` | Derive required changes from `POLICY_ACTIONS`; added POL-002 to that table | POL-002 mandates the billing team **at normal priority**; the task required only the team. An agent that applied the policy exactly was failed for an undeclared mutation. The intended trap (do not escalate) was avoided correctly in all 3 repeats - the task failed on the part it got right. |
| 11 | 2026-08-13 | tool/runtime defect | `search_tickets` (contract v1 -> v2) | `customer_name` is a documented case-insensitive substring match, matching `query` | Two free-text filters on one tool had different, undocumented matching semantics. `customer_name="013"` returned `SUCCESS_EMPTY`, which under the adopted `accept_empty` policy correctly tells the agent to stop - a partial name became a silent dead end. Fourth instance of [SILENT_TOOL_FAILURE](SILENT_TOOL_FAILURE.md). |

## Rebalancing passes

One intentional difficulty/fairness rebalancing pass is permitted before the
freeze. **None used so far.**

| Pass | Date | Scope | Outcome |
|---|---|---|---|
| 1 (the single permitted pass) | 2026-08-13 | Composition/difficulty **expansion**: added 5 structurally harder families. No existing task modified, none removed for being easy. | 33 → 60 tasks. **Did not achieve its goal.** The hard tier measured 49.2% only while three benchmark defects were present; after edits 9–11 it measures **96.2%**. See below. |

### Amended rule

The pass was redefined before use (docs/P3_SUITE_COMPOSITION.md §1) because the
situation it was written for never occurred. Trigger: the measured ceiling after
substrate defects were removed. Scope: add harder families. Explicitly out of
scope: editing a task because the agent passes it.

### Measured effect — the expansion did not create difficulty

The first hard-tier calibration read 49.2%, and I recorded that as restored
discrimination. **That was wrong.** Three benchmark defects were suppressing the
score (edits 9–11), the largest being a fixture in which no ticket was uniquely
identifiable by customer and issue. After fixing them, on the same commit, same
model, same 14-turn budget:

| Tier | Before fixes (defective) | After fixes | Reading |
|---|---:|---:|---|
| core | 97.0% | **98.0%** | unchanged; regression canary works |
| **hard** | 49.2% | **96.2%** | the difficulty was measurement error |

Per family after fixes: `distractor_resolution` 85.7%, `conditional_escalation`
88.9%, **every other family 100%**. Per-task consistency over 3 repeats: 57 of 60
pass 3/3, two are intermittent, one fails 3/3.

The one deterministic failure (`SUP-distract-005`) was inspected and is **genuine
agent weakness**, not a defect: the agent picked Customer 002's *billing* ticket
when the prompt asked for their shipping ticket, apparently matching the ticket
number to the customer number. It stays.

**Conclusion: the suite is saturated for this model at ~97%, and the single
permitted rebalancing pass is now spent.** Task-level success is not a
discriminating metric here. That is a measured result and it is reported as one —
no further difficulty tuning is permitted, and manufacturing harder tasks to
produce a lower number would be fitting the benchmark to a desired figure.

### What still discriminates

Call-level behaviour, which is independent of task success:

| Signal | Measured | Pre-registered threshold | Selected? |
|---|---:|---|:--:|
| invalid typed calls | **49/930 = 5.27%** | ≥2% of calls | yes |
| episodes with ≥1 invalid call | **49/180 = 27.2%** | ≥15% of episodes | yes |

Both thresholds were fixed before these numbers existed, and both clear. **The
schema-repair intervention is selected by the pre-registered rule.** Its outcome
metrics are call-level and efficiency-level, where headroom exists, rather than
task success, where it does not.
