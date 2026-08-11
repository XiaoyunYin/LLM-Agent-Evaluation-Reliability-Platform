/**
 * Claim readiness.
 *
 * Each entry is a sentence someone might put on a resume, paired with the
 * measurement that would have to exist for it to be true. Nothing here is
 * hand-flagged as met or unmet — `evaluate()` recomputes every verdict from
 * the snapshot. Paste a real number into metricsSnapshot.ts and the
 * corresponding row flips by itself.
 *
 * That inversion is the point. A checklist you tick manually drifts from
 * reality the moment you stop being careful; a checklist derived from the
 * data cannot.
 */

import {
  generation,
  infrastructure,
  judging,
  providerCoverage,
  retrievalStrategies,
  ci,
} from './metricsSnapshot'
import { measuredValue } from '../types/provenance'

export interface ClaimVerdict {
  id: string
  claim: string
  /** The project rule (.editor-rules.md) that guards this claim. */
  guard: string
  met: boolean
  /** What is true right now — the honest one-liner. */
  evidence: string
}

export function evaluateClaims(): ClaimVerdict[] {
  const bulkJudged = measuredValue(judging.bulkJudgedAnswers) ?? 0
  const spanDocs = measuredValue(infrastructure.traceSpanDocuments) ?? 0
  const tokensPerSecond =
    measuredValue(infrastructure.vllmThroughputTokensPerSecond) ?? 0
  const agreement = measuredValue(judging.passFailAgreement)
  const realProviderRuns =
    measuredValue(generation.full120CaseRunsWithRealProviders) ?? 0

  const realProviders = providerCoverage.filter(
    (p) => p.countsAsRealDiversity && (measuredValue(p.persistedAnswers) ?? 0) > 0,
  )

  const hybridMeasured = retrievalStrategies
    .filter((s) => s.key === 'hybrid' || s.key === 'dense')
    .every((s) => measuredValue(s.recallAt10) !== undefined)

  return [
    {
      id: 'retrieval-comparison',
      claim: 'Hybrid RRF retrieval compared against dense-only and BM25-only on the same held-out 120-query set',
      guard: 'Rule 19 — an unmeasured metric is a target, not a result',
      met: hybridMeasured,
      evidence: hybridMeasured
        ? 'Dense and hybrid recall@10 are both measured.'
        : 'Only BM25 has been measured. Dense and hybrid returned status=not_run without an embedding key.',
    },
    {
      id: 'provider-diversity',
      claim: 'Candidate answers generated through both the OpenAI and Anthropic APIs',
      guard: 'Rule 46 — no API coverage claim without real candidate answers from both',
      met: realProviders.length >= 2,
      evidence:
        realProviders.length >= 2
          ? `Real answers persisted from ${realProviders.map((p) => p.provider).join(' and ')}.`
          : `0 of 2 real providers have persisted answers. ${realProviderRuns} full 120-case runs used a real provider.`,
    },
    {
      id: 'run-matrix',
      claim: `${generation.targetFull120CaseRuns}+ full 120-case runs across the matrix`,
      guard: 'Rule 24 — candidate answers exist before judging',
      met: (measuredValue(generation.full120CaseRuns) ?? 0) >= generation.targetFull120CaseRuns,
      evidence: `${measuredValue(generation.full120CaseRuns) ?? 0} of ${generation.targetFull120CaseRuns} full 120-case runs exist on disk, and all of them are mock-provider rehearsals.`,
    },
    {
      id: 'bulk-judging',
      claim: `${judging.targetBulkJudged.toLocaleString()}+ answers judged by the self-hosted 7B judge`,
      guard: 'Rule 40 — no 8K+ claim below 8,000 persisted judge scores',
      met: bulkJudged >= judging.targetBulkJudged,
      evidence: `${bulkJudged.toLocaleString()} bulk judge scores persisted. The 7B judge has only ever run against a mock HTTP endpoint.`,
    },
    {
      id: 'judge-agreement',
      claim: `${Math.round(judging.targetAgreement * 100)}% dual-judge agreement on the 120-answer validation slice`,
      guard: 'Rule 35 — no agreement claim without GPT-4o-mini vs the real 7B judge',
      met: agreement !== undefined,
      evidence:
        agreement !== undefined
          ? `Measured at ${(agreement * 100).toFixed(1)}% on n=120 — report it with a confidence interval.`
          : 'The only agreement figure so far came from a stand-in judge against a mock endpoint. It measures the harness.',
    },
    {
      id: 'tracing',
      claim: `${infrastructure.targetTraceDocuments.toLocaleString()}+ traces across six instrumented service layers`,
      guard: 'Rule 41 — no 10K+ trace claim without 10,000 documents in Elasticsearch',
      met: spanDocs >= infrastructure.targetTraceDocuments,
      evidence: `Six layers are instrumented and asserted by tests, but ${spanDocs.toLocaleString()} span documents have been counted in Elasticsearch.`,
    },
    {
      id: 'throughput',
      claim: `Sustained ${infrastructure.targetThroughput} tok/s at concurrency ${infrastructure.benchmarkConcurrency} on g4dn.xlarge / T4`,
      guard: 'Rules 42–44 — throughput and bulk-judged count are separate measurements',
      met: tokensPerSecond >= infrastructure.targetThroughput,
      evidence:
        tokensPerSecond > 0
          ? `Benchmarked at ${tokensPerSecond} tok/s.`
          : 'No GPU window has happened. Even once measured, do not grammatically tie tok/s to the bulk run unless the bulk run itself was instrumented.',
    },
    {
      id: 'ci-gate',
      claim: `CI blocks changes that regress eval score >${ci.evalScoreRegressionThreshold * 100}% or latency/cost >${ci.latencyCostRegressionThreshold * 100}%`,
      guard: 'Rule 45 — no CI gating claim until CI blocks a fake regression',
      met: measuredValue(ci.regressionGate) !== undefined,
      evidence: 'No .github/workflows directory exists. Nothing blocks anything yet.',
    },
  ]
}
