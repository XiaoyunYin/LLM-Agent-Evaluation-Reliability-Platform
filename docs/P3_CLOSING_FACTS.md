# P3 Closing Facts

Written before P4 implementation. These facts close the P3 ledger from artifacts
rather than inferred arithmetic.

Sources:

- `config/p3_frozen_manifest.json`
- `runs/support_baseline/frozen_baseline.json`
- `runs/support_baseline/repair_experiment.json`
- `config/p3_repair_cohort.json`
- `runs/support_benchmark/support_b3_01..support_b3_10/`

## Frozen Suite Composition

Suite hash: `2cfcaedbb4005e6d2ff52bcc69396dfffbb9ce1758c48b04945335d6478f396b`.

The frozen suite contains 80 tasks: 35 core and 45 hard. The counts below are
from the generated frozen task specs and the manifest composition, not inferred
from `350 + 450` episode cells.

Core task IDs, 35:

`SUP-cond-001`, `SUP-cond-002`, `SUP-cond-003`, `SUP-cond-004`,
`SUP-cond-005`, `SUP-cond-006`, `SUP-lookup-001`, `SUP-lookup-002`,
`SUP-lookup-003`, `SUP-lookup-004`, `SUP-lookup-005`, `SUP-lookup-006`,
`SUP-lookup-007`, `SUP-lookup-008`, `SUP-multi-001`, `SUP-multi-002`,
`SUP-multi-003`, `SUP-multi-004`, `SUP-multi-005`, `SUP-multi-006`,
`SUP-multiticket-001`, `SUP-multiticket-002`, `SUP-multiticket-003`,
`SUP-policy-001`, `SUP-policy-002`, `SUP-policy-003`, `SUP-policy-004`,
`SUP-simple-001`, `SUP-simple-002`, `SUP-simple-003`, `SUP-simple-004`,
`SUP-simple-005`, `SUP-simple-006`, `SUP-simple-007`, `SUP-simple-008`.

Hard task IDs, 45:

`SUP-chain-001`, `SUP-chain-002`, `SUP-chain-003`, `SUP-chain-004`,
`SUP-chain-005`, `SUP-chain-006`, `SUP-chain-007`, `SUP-chain-008`,
`SUP-chain-009`, `SUP-chain-010`, `SUP-distract-001`, `SUP-distract-002`,
`SUP-distract-003`, `SUP-distract-004`, `SUP-distract-006`,
`SUP-distract-007`, `SUP-distract-008`, `SUP-distract-009`,
`SUP-distract-010`, `SUP-mtcond-001`, `SUP-mtcond-002`, `SUP-mtcond-003`,
`SUP-mtcond-004`, `SUP-mtcond-005`, `SUP-mtcond-006`, `SUP-mtcond-007`,
`SUP-mtcond-008`, `SUP-noop-001`, `SUP-noop-002`, `SUP-noop-003`,
`SUP-noop-004`, `SUP-noop-005`, `SUP-noop-006`, `SUP-noop-007`,
`SUP-noop-008`, `SUP-polsel-001`, `SUP-polsel-002`, `SUP-polsel-003`,
`SUP-polsel-004`, `SUP-polsel-005`, `SUP-polsel-006`, `SUP-polsel-007`,
`SUP-polsel-008`, `SUP-polsel-009`, `SUP-polsel-010`.

Core + hard = 80.

## Baseline Numerators

Frozen baseline runs: `support_b3_01` through `support_b3_10`.

| Scope | Passes / total episode cells | Success |
|---|---:|---:|
| Global | 722 / 800 | 90.25% |
| Core | 342 / 350 | 97.71% |
| Hard | 380 / 450 | 84.44% |

## Complete Family Table

Consistency is measured across the 10 frozen repeats at task granularity.

| family_id | tier | tasks | passes / cells | pooled success | consistency |
|---|---|---:|---:|---:|---|
| `conditional_escalation` | core | 6 | 52 / 60 | 86.67% | always 4, never 0, intermittent 2; pass-counts `6/10:2`, `10/10:4` |
| `lookup_update` | core | 8 | 80 / 80 | 100.00% | always 8, never 0, intermittent 0; pass-counts `10/10:8` |
| `multi_field` | core | 6 | 60 / 60 | 100.00% | always 6, never 0, intermittent 0; pass-counts `10/10:6` |
| `multi_ticket` | core | 3 | 30 / 30 | 100.00% | always 3, never 0, intermittent 0; pass-counts `10/10:3` |
| `policy_update` | core | 4 | 40 / 40 | 100.00% | always 4, never 0, intermittent 0; pass-counts `10/10:4` |
| `simple_update` | core | 8 | 80 / 80 | 100.00% | always 8, never 0, intermittent 0; pass-counts `10/10:8` |
| `chained_resolution` | hard | 10 | 100 / 100 | 100.00% | always 10, never 0, intermittent 0; pass-counts `10/10:10` |
| `distractor_resolution` | hard | 9 | 82 / 90 | 91.11% | always 7, never 0, intermittent 2; pass-counts `3/10:1`, `9/10:1`, `10/10:7` |
| `multi_ticket_conditional` | hard | 8 | 18 / 80 | 22.50% | always 0, never 5, intermittent 3; pass-counts `0/10:5`, `2/10:1`, `8/10:2` |
| `noop_plus_mutation` | hard | 8 | 80 / 80 | 100.00% | always 8, never 0, intermittent 0; pass-counts `10/10:8` |
| `policy_selection` | hard | 10 | 100 / 100 | 100.00% | always 10, never 0, intermittent 0; pass-counts `10/10:10` |

The denominator behind `multi_ticket_conditional = 22.5%` is 80 episode cells:
8 tasks crossed with 10 frozen repeats. The numerator is 18 passing cells.

## Intervention Arm Sizes

The P3 schema-repair intervention used one bridge/control run and four treatment
runs after the 10 frozen baseline runs.

| Arm | Runs | Global episodes | Global passes / total | Cohort episodes | Cohort passes / total |
|---|---:|---:|---:|---:|---:|
| Baseline OFF | 10 | 800 | 722 / 800 = 90.25% | 250 | 240 / 250 = 96.00% |
| Bridge OFF, treatment commit | 1 | 80 | 74 / 80 = 92.50% | 25 | 24 / 25 = 96.00% |
| Treatment ON | 4 | 320 | 289 / 320 = 90.31% | 100 | 93 / 100 = 93.00% |

The exact numerator/denominator behind `90.25% -> 90.31%` is therefore
`722/800 -> 289/320`. The comparison is unchanged in substance and remains a null
verdict; these are different arm sizes, not paired equal-denominator cells.

## Amended Intervention-Selection Doctrine

P3 selected schema repair by an incidence-only trigger: invalid typed calls were
at least the configured fraction of tool calls, or occurred in at least the
configured fraction of episodes. That rule fired.

The replacement rule for future interventions is consequence-based. Before
selecting a repair, ask:

- Does the failure remain unresolved?
- Does it cause task failure?
- Does it materially increase steps or cost?
- Does it create an unsafe side effect?

Artifact-backed P3 values:

| Quantity | Value |
|---|---:|
| invalid-call incidence | 235 / 4,545 = 5.17% |
| episodes with invalid calls | 235 / 800 = 29.38% |
| next tool call valid after the validation error | 235 / 235 |
| second invalid call in the same episode | 0 / 235 |
| unrecovered invalid-call consequence | 0 |

Under the amended rule, schema repair would not have been selected: the incidence
was real, but every observed invalid call was recovered before a repeated invalid
call occurred. This does not rewrite the P3 history; it records the lesson for
the next pre-registration.

## Parked P3 Capability Signal

`multi_ticket_conditional` is preserved at 18/80 = 22.5%. The trajectory diagnosis
also stays preserved: the agent applies the priority half of each policy and not
the team half on `SUP-mtcond-001` through `SUP-mtcond-004`, and over-applies the
enterprise outage rule on `SUP-mtcond-007`.

Do not fix this before P4. It is candidate material for a later agent-policy
intervention, not part of durability or crash-safety work.
