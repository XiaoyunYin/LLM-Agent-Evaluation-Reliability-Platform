# Claims and Evidence

This ledger keeps the public story tied to a measured result and its scope. Raw
run output is generated locally; the reports and audit scripts in this repository
are the public summaries.

## 1. Spider SQL-agent baseline

**Claim:** On the 1,034-task Spider development set, the tool-using agent
achieved 65.38% test-suite execution accuracy and 73.31% single-database
execution accuracy.

**Evidence:** [P0 results](results/spider-p0.md),
[benchmark protocol](benchmark-protocol.md), and
[`scripts/audit_p0_claims.py`](../scripts/audit_p0_claims.py).

**Scope:** The agent discovers database schema through tools. This is an internal
agent baseline, not a direct comparison with the public Spider leaderboard.

## 2. Repeat variance and regression policy

**Claim:** Four same-commit P1 repeats had a maximum spread of 1.35 percentage
points. The CI gate uses a 2.71-point failure threshold for the primary score.

**Evidence:** [P1 results](results/p1-frozen.md),
[`metrics/spider_gate_policy.json`](../metrics/spider_gate_policy.json), and
[`scripts/check_spider_gate.py`](../scripts/check_spider_gate.py).

**Scope:** Four repeats estimate a practical noise envelope; they do not support
distributional or confidence-interval claims.

## 3. Targeted SQL-agent change

**Claim:** On a 39-task cohort frozen before treatment, completion increased from
19.23% to 71.79% after the agent was reminded to submit a query it had already
executed successfully.

**Evidence:** [P2 results](results/p2-frozen.md) and the versioned configuration
under `config/`.

**Scope:** This is a targeted cohort result, not a claim of the same improvement
on all Spider tasks.

## 4. Stateful support agent

**Claim:** The 80-task support-ticket suite reached 90.25% mean success over ten
repeats and 800 episodes. The verifier checks required, allowed, and forbidden
database changes directly.

**Evidence:** [P3 results](results/p3-frozen.md),
[`config/p3_frozen_manifest.json`](../config/p3_frozen_manifest.json), and
[`docs/P3_CONTRACT_V0.md`](P3_CONTRACT_V0.md).

**Scope:** The suite is small and partly saturated for the tested model. A
pre-registered schema-repair intervention did not produce a measurable effect;
the project does not claim that it did.

## 5. Crash recovery

**Claim:** The deterministic P4a matrix passed 915/915 cases, including 835
injected crashes, with no lost or duplicate business effects and no incorrect
final state.

**Evidence:** [P4a matrix results](results/p4a-matrix.md),
[P4a audit](results/p4a-audit.md), and
[`scripts/run_p4a_matrix.py`](../scripts/run_p4a_matrix.py).

**Scope:** P4a is a Python, single-host durability harness. It does not establish
distributed stale-worker fencing, poison/DLQ behavior, or Java integration.

## 6. Retrieval

**Claim:** On the evaluated BEIR slices, hybrid retrieval improved SciFact recall
at 10 by 2.8% and nDCG at 10 by 3.1% relative to the strongest single retriever;
NFCorpus was effectively tied.

**Evidence:** The retrieval scripts, versioned labels, and the claims summarized
in the repository README.

**Scope:** Retriever parameters were selected on each dataset's training split
and evaluated on its held-out split. The result is corpus-specific rather than a
general claim about hybrid retrieval.

## 7. Candidate generation and judge validation

**Claim:** The published RAG matrix contains 79 completed runs with 9,480
generated and judged answers. In a 120-answer dual-judge slice, the judges agreed
on 65.0% of pass/fail decisions, with Cohen's kappa of 0.264 and 52 cases routed
for manual review.

**Evidence:** [candidate-generation results](results/candidate-generation.md),
[scale results](results/scale-runs.md), and the dashboard fixtures under
`runs/gpu_window_rehearsal/`.

**Scope:** Judge agreement measures consistency between judges, not correctness
against a human-labeled standard. Superseded or invalid fixtures are excluded
from the headline totals.

## Reporting rules

- A result is claimable only when its workload, metric, and validity boundary are
  stated.
- Different phases and workloads are not combined into one quality score.
- Raw run files and downloaded datasets are local reproducibility inputs, not
  part of the public source tree.
- Improvements are not generalized beyond the task family and treatment that
  produced them.
- When an experiment was invalid, superseded, or inconclusive, the report says so
  instead of presenting it as a positive result.
