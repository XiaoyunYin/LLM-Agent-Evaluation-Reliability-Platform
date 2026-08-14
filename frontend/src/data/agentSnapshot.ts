/**
 * AGENT EVALUATION SNAPSHOT — P0 through P4a.
 *
 * Same rules as metricsSnapshot.ts: nothing here is typed in from memory. Every
 * figure was read out of a persisted artifact, and the `command` argument is the
 * one that regenerates it.
 *
 * The distinction that matters most on this page: P0 and P3 measure *different
 * things*. P0 grades a query — did the SQL return gold's rows. P3 grades an
 * effect on the world — did the database end up in the state the task declared.
 * They are not two runs of one benchmark and their numbers must never be pooled.
 *
 * Verified against the artifacts on 2026-08-14.
 */

import { measured, type Metric } from '../types/provenance'

/* ------------------------------------------------------------------ */
/* P0 — Spider SQL agent, execution-verified                           */
/* ------------------------------------------------------------------ */

const P0_RUN = 'runs/spider_benchmark/spider_full__p0_v2'

export const spiderAgent = {
  tasks: measured(
    1034,
    `${P0_RUN}/p0_metrics.json — full Spider 1.0 dev split, 20 databases, 0 excluded`,
    '2026-08-13',
    'python scripts/report_spider_metrics.py --run-id spider_full__p0_v2',
  ),
  singleDbAccuracy: measured(
    0.7331,
    `${P0_RUN} — 758/1034 episodes whose final SQL matched gold on the task's own database`,
    '2026-08-13',
    'python scripts/audit_p0_claims.py --run-id spider_full__p0_v2',
  ),
  testSuiteAccuracy: measured(
    0.654,
    `${P0_RUN}/rescore__test_suite.json — same SQL rescored against 695 distilled database instances; passes only if it matches gold on every one`,
    '2026-08-13',
    'python scripts/rescore_with_substrate.py --run-id spider_full__p0_v2 --substrate test_suite',
  ),
  falsePositiveRate: measured(
    0.108,
    `${P0_RUN}/rescore__test_suite.json — movement_vs_original_metric: 82 pass_to_fail of 758 single-database passes, and 0 fail_to_pass. Zero movement in the other direction is what a strictly tighter metric must show`,
    '2026-08-13',
    'python scripts/rescore_with_substrate.py --run-id spider_full__p0_v2 --substrate test_suite',
  ),
  infrastructureFailures: measured(
    0,
    `${P0_RUN} — MODEL_ERROR + TOOL_ERROR + NO_FINAL_SQL across all 1,034 episodes`,
    '2026-08-13',
    'python scripts/report_spider_metrics.py --run-id spider_full__p0_v2',
  ),
  costPerSuccess: measured(
    0.000813,
    'Total estimated benchmark cost $0.616408 / 758 successes. Estimated from published list price, not a billed invoice',
    '2026-08-13',
    'python scripts/audit_p0_claims.py --run-id spider_full__p0_v2',
  ),
} satisfies Record<string, Metric<number>>

/**
 * Termination reasons. These sum to exactly 1,034 — including the zeros.
 *
 * Counts are `Metric<number>` rather than bare numbers on purpose. A zero here is
 * a *measured* zero — no model, tool or evaluator failure occurred — and that is a
 * different fact from "not measured". The union is what stops the two collapsing
 * into the same rendered cell.
 */
const termination = (count: number, jsonPath: string) =>
  measured(
    count,
    `${P0_RUN}/p0_metrics.json — ${jsonPath}`,
    '2026-08-13',
    'python scripts/report_spider_metrics.py --run-id spider_full__p0_v2',
  )

/**
 * Note the paths. `termination_counts` only contains reasons that OCCURRED — it
 * has four keys, not seven. The three zeros are recorded in their own fields
 * (`model_failures`, `tool_failures`, `missing_final_sql`), because "this did not
 * happen" is asserted separately from "here is what happened".
 *
 * An earlier version of this file pointed all seven at
 * `termination_counts.<reason>`, which does not resolve for the zeros. A
 * provenance path that does not exist is worse than none: it reads as checkable
 * and is not.
 */
export const spiderTerminations = [
  { key: 'success', label: 'SUCCESS', count: termination(758, 'failure_breakdown.termination_counts.SUCCESS') },
  { key: 'verification', label: 'VERIFICATION_FAILED', count: termination(226, 'failure_breakdown.termination_counts.VERIFICATION_FAILED') },
  { key: 'maxsteps', label: 'MAX_STEPS', count: termination(48, 'failure_breakdown.termination_counts.MAX_STEPS') },
  { key: 'sqlerror', label: 'SQL_ERROR', count: termination(2, 'failure_breakdown.termination_counts.SQL_ERROR') },
  { key: 'modelerror', label: 'MODEL_ERROR', count: termination(0, 'failure_breakdown.model_failures') },
  { key: 'toolerror', label: 'TOOL_ERROR', count: termination(0, 'failure_breakdown.tool_failures') },
  { key: 'nofinalsql', label: 'NO_FINAL_SQL', count: termination(0, 'failure_breakdown.missing_final_sql') },
]

/* ------------------------------------------------------------------ */
/* P3 — stateful agent benchmark, verified state diffs                 */
/* ------------------------------------------------------------------ */

export const statefulAgent = {
  tasks: measured(
    80,
    'config/p3_frozen_manifest.json — 35 core / 45 hard, pinned by content hash',
    '2026-08-14',
    'python -m scripts.assert_p3_frozen',
  ),
  successRate: measured(
    0.9025,
    'runs/support_baseline/frozen_baseline.json — 10 repeats, 800 episodes, sd 1.75%',
    '2026-08-13',
    'python -m scripts.analyze_p3_baseline --runs support_b3_01 support_b3_02 support_b3_03 support_b3_04 support_b3_05 support_b3_06 support_b3_07 support_b3_08 support_b3_09 support_b3_10',
  ),
  coreTier: measured(
    0.977,
    '342/350 — the regression canary tier. A drop here signals a regression in the evaluated system or the harness (agent, prompt, tool contract, model behaviour, or substrate), not that the benchmark became harder — the suite is frozen by content hash',
    '2026-08-13',
    'python -m scripts.analyze_p3_baseline --runs support_b3_01 support_b3_02 support_b3_03 support_b3_04 support_b3_05 support_b3_06 support_b3_07 support_b3_08 support_b3_09 support_b3_10',
  ),
  hardTier: measured(
    0.844,
    '380/450 — declared the primary discrimination metric before any baseline ran',
    '2026-08-13',
    'python -m scripts.analyze_p3_baseline --runs support_b3_01 support_b3_02 support_b3_03 support_b3_04 support_b3_05 support_b3_06 support_b3_07 support_b3_08 support_b3_09 support_b3_10',
  ),
  verifierQa: measured(
    452,
    'runs/support_verifier_qa/verifier_qa.json — 452/452, including adversarial known-bad cases: partial completion, wrong value, unrelated mutation, forbidden mutation',
    '2026-08-14',
    'python -m scripts.qa_support_verifier',
  ),
  referenceReplays: measured(
    80,
    'runs/support_reference_replay/reference_replay.json — 80/80 reference solutions replayed through the real runtime with zero model calls',
    '2026-08-14',
    'python -m scripts.replay_support_references',
  ),
} satisfies Record<string, Metric<number>>

/** Per-family success. Eight of eleven sit at 100% — the suite is saturated. */
export const statefulFamilies = [
  { key: 'mtcond', label: 'multi_ticket_conditional', tier: 'hard', rate: 0.225 },
  { key: 'cond', label: 'conditional_escalation', tier: 'core', rate: 0.867 },
  { key: 'distract', label: 'distractor_resolution', tier: 'hard', rate: 0.911 },
  { key: 'simple', label: 'simple_update', tier: 'core', rate: 1 },
  { key: 'lookup', label: 'lookup_update', tier: 'core', rate: 1 },
  { key: 'policyupd', label: 'policy_update', tier: 'core', rate: 1 },
  { key: 'multifield', label: 'multi_field', tier: 'core', rate: 1 },
  { key: 'multiticket', label: 'multi_ticket', tier: 'core', rate: 1 },
  { key: 'chain', label: 'chained_resolution', tier: 'hard', rate: 1 },
  { key: 'policysel', label: 'policy_selection', tier: 'hard', rate: 1 },
  { key: 'noop', label: 'noop_plus_mutation', tier: 'hard', rate: 1 },
]

/* ------------------------------------------------------------------ */
/* P4a — durability under injected crashes                             */
/* ------------------------------------------------------------------ */

const P4A = 'runs/p4a_matrix/p4a_matrix_20260813/p4a_matrix.json'

export const durability = {
  totalCases: measured(
    915,
    `${P4A} — 167 effectful steps x 5 crash windows (835) + 80 clean controls`,
    '2026-08-13',
    'python -m scripts.run_p4a_matrix --run-id p4a_matrix_20260813',
  ),
  crashCases: measured(
    835,
    `${P4A} — a crash injected at every one of five windows around every mutating step`,
    '2026-08-13',
    'python -m scripts.run_p4a_matrix --run-id p4a_matrix_20260813',
  ),
  passed: measured(
    915,
    `${P4A} — every recovered world verified by the same P3 snapshot-diff verifier, not by the harness's own bookkeeping`,
    '2026-08-13',
    'python -m scripts.audit_p4a_matrix --artifact runs/p4a_matrix/p4a_matrix_20260813/p4a_matrix.json',
  ),
  modelCalls: measured(
    0,
    'Deterministic replay of frozen reference trajectories — no model is involved, so the result is reproducible',
    '2026-08-13',
    'python -m scripts.run_p4a_matrix --run-id p4a_matrix_20260813',
  ),
} satisfies Record<string, Metric<number>>

/**
 * The acceptance counters. All zero is the entire claim — which is exactly why
 * each one carries provenance rather than being a literal `0` in a table.
 */
const counter = (name: string) =>
  measured(
    0,
    `${P4A} — summary.acceptance_totals.${name}, across all 915 cases`,
    '2026-08-13',
    'python -m scripts.audit_p4a_matrix --artifact runs/p4a_matrix/p4a_matrix_20260813/p4a_matrix.json',
  )

export const durabilityCounters = [
  { key: 'dupe', label: 'duplicate_side_effects', meaning: 'the same business mutation applied twice', value: counter('duplicate_side_effects') },
  { key: 'lost', label: 'lost_required_effects', meaning: 'a required mutation never landed', value: counter('lost_required_effects') },
  { key: 'state', label: 'incorrect_final_states', meaning: 'the recovered world is not what the task required', value: counter('incorrect_final_states') },
  { key: 'orphan', label: 'orphan_effect_records', meaning: 'an effect recorded with no durable intent — write-ahead ordering violated', value: counter('orphan_effect_records') },
  { key: 'stale', label: 'stale_fenced_effects_accepted', meaning: "a fenced-out worker's write was accepted", value: counter('stale_fenced_effects_accepted') },
  { key: 'invariant', label: 'invariant_violations', meaning: 'any protocol invariant broken', value: counter('invariant_violations') },
]

/* ------------------------------------------------------------------ */
/* The armed regression gate                                           */
/* ------------------------------------------------------------------ */

/**
 * Each threshold is `max(2 x observed_spread, minimum_detectable_change)` across
 * four same-commit repeats. The superseded policy was ">5% eval score", chosen by
 * judgement — about 3.7x wider than the noise it was meant to sit above.
 */
/**
 * `spread` is measured — the observed range across four same-commit repeats.
 * `threshold` is *policy* derived from it, and is read from
 * metrics/spider_gate_policy.json rather than measured, so it is a plain number
 * here. Keeping the distinction visible matters: one is an observation, the other
 * is a decision made about that observation.
 */
const spread = (value: number, metric: string) =>
  measured(
    value,
    `metrics/spider_gate_policy.json — gate.metrics.${metric}.observed_spread, the range across four same-commit repeats (spider_rpt__on_1..4)`,
    '2026-08-13',
    'python -m scripts.analyze_run_variance --run spider_rpt__on_1 --run spider_rpt__on_2 --run spider_rpt__on_3 --run spider_rpt__on_4',
  )

export const gateMetrics = [
  {
    key: 'accuracy',
    label: 'test_suite_task_success',
    threshold: 0.027079,
    spread: spread(0.01354, 'test_suite_task_success'),
    direction: 'decrease is bad',
    armed: true,
  },
  {
    key: 'turns',
    label: 'mean_model_turns_per_success',
    threshold: 0.055692,
    spread: spread(0.027846, 'mean_model_turns_per_success'),
    direction: 'increase is bad',
    armed: true,
  },
  {
    key: 'validity',
    label: 'tool_validity_rate',
    threshold: 0.001912,
    spread: spread(0.000956, 'tool_validity_rate'),
    direction: 'decrease is bad',
    armed: true,
  },
  {
    key: 'cost',
    label: 'estimated_cost_per_success',
    threshold: 0.00008,
    spread: spread(0.00004, 'estimated_cost_per_success'),
    direction: 'increase is bad',
    armed: true,
  },
  {
    key: 'passk',
    label: 'consistency_pass_pow_4',
    threshold: null,
    spread: null,
    direction: 'decrease is bad',
    armed: false,
  },
]

export const gateVerification = {
  /**
   * The command is the TEST, not `check_spider_gate` — running the gate against
   * the committed metrics passes, because the committed metrics are not regressed.
   * A command that returns GATE PASSED cannot evidence a block. The test injects
   * the regression and asserts the failure, so it reproduces the property on
   * demand; the pull request that was actually blocked is corroboration, not
   * something a reader can re-run.
   */
  blockedRegression: measured(
    0.04,
    'tests/test_spider_gate.py::test_each_armed_metric_fails_when_it_regresses — a 4pp move, about 1.5x the 0.027079 threshold, fails the gate. Separately observed in CI: a pull request carrying that regression failed regression-gate and could not be merged',
    '2026-08-14',
    'pytest tests/test_spider_gate.py -q -k regresses',
  ),
  gateTests: measured(
    23,
    'tests/test_spider_gate.py — one failing case per armed metric, one per always-fail condition, plus proof that movement inside a threshold passes',
    '2026-08-14',
    'pytest tests/test_spider_gate.py -q',
  ),
} satisfies Record<string, Metric<number>>

/* ------------------------------------------------------------------ */
/* Observability                                                       */
/* ------------------------------------------------------------------ */

export const observability = {
  spanDocuments: measured(
    225015,
    'Elasticsearch otel-traces data stream, status GREEN. Every document carries telemetry.sdk.name=opentelemetry, version 1.44.0',
    '2026-08-14',
    'curl -s -XPOST localhost:9200/otel-traces/_search -d \'{"size":0,"track_total_hits":true}\'',
  ),
  p0TrajectoryRecords: measured(
    10432,
    'runs/spider_benchmark/spider_full__p0_v2/steps.jsonl',
    '2026-08-13',
    'python scripts/report_spider_metrics.py --run-id spider_full__p0_v2 --check-traces',
  ),
  p0Spans: measured(
    13832,
    'Reconciles exactly: 10,432 step records + 1 eval.run + 1,034 agent.episode + 1,379 sqlite.query + 986 verifier.execution',
    '2026-08-13',
    'python scripts/report_spider_metrics.py --run-id spider_full__p0_v2 --check-traces',
  ),
} satisfies Record<string, Metric<number>>
