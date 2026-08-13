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

## Rebalancing passes

One intentional difficulty/fairness rebalancing pass is permitted before the
freeze. **None used so far.**

| Pass | Date | Scope | Outcome |
|---|---|---|---|
| — | — | — | not yet run |
