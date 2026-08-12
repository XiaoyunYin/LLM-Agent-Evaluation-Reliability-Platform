/**
 * THE MEASUREMENT SNAPSHOT — this is the file you edit as you measure things.
 *
 * Nothing in the UI hardcodes a number. Every figure the dashboard shows comes
 * from here, and every figure here is tagged with how it was obtained.
 *
 * Rules for editing this file:
 *   1. Only promote something to `measured(...)` after you have run the code
 *      and seen the output. Paste the command into the third argument.
 *   2. Never turn a `notMeasured(...)` into `measured(0, ...)` to make a chart
 *      look full. A missing measurement is not a zero.
 *   3. Mock-provider and mock-judge results are NOT measurements of the thing
 *      they stand in for. They stay `notMeasured` with a note explaining what
 *      the mock proved (plumbing) and what it did not (quality).
 *
 * Current values were transcribed from docs/build-log.md sessions 3–36 and
 * verified against the files on disk on 2026-08-05.
 */

import {
  measured,
  notMeasured,
  placeholder,
  type Metric,
} from '../types/provenance'

/* ------------------------------------------------------------------ */
/* Corpus & datasets                                                   */
/* ------------------------------------------------------------------ */

export const corpus = {
  documents: measured(
    1204,
    'SQuAD v2 dev paragraphs — the evaluation corpus retrieval is scored against',
    '2026-08-12',
    'python scripts/load_squad_dataset.py',
  ),
  chunks: measured(
    1204,
    'One chunk per paragraph; BEIR-style document-level retrieval',
    '2026-08-12',
    'wc -l < datasets/squad_v2/chunks.jsonl',
  ),
  distinctChunkTexts: measured(
    1204,
    'Deduplicated by construction — paragraph IDs hash the paragraph text',
    '2026-08-12',
    'python scripts/analyze_corpus_duplication.py',
  ),
  chunksIndexedInElasticsearch: measured(
    1204,
    'Indexed as squad_v2_chunks',
    '2026-08-12',
    'python scripts/index_chunks_to_elasticsearch.py --index squad_v2_chunks',
  ),
  chunkSizeChars: measured(650, 'Session 19 chunking config', '2026-08-02'),
  chunkOverlapChars: measured(100, 'Session 19 chunking config', '2026-08-02'),
} satisfies Record<string, Metric>

export const datasets = {
  goldenRagCases: measured(
    120,
    'Session 4 — dataset_loader over golden_rag_v0.2.jsonl',
    '2026-07-30',
    'python -m backend.app.dataset_loader datasets/golden/golden_rag_v0.2.jsonl',
  ),
  heldOutLabeledQueries: measured(
    120,
    'Session 21 — strict label validator',
    '2026-08-02',
    'python scripts/validate_retrieval_labels.py --strict',
  ),
  relevantChunkReferences: measured(
    180,
    'Session 21 — strict label validator',
    '2026-08-02',
  ),
  unknownChunkIds: measured(
    0,
    'Session 21 — strict label validator',
    '2026-08-02',
  ),
  agenticToolCases: measured(
    2,
    'Session 27 — golden_agentic_tools_v0.1.jsonl',
    '2026-08-02',
  ),
} satisfies Record<string, Metric>

/* ------------------------------------------------------------------ */
/* Retrieval benchmark                                                 */
/* ------------------------------------------------------------------ */

export interface RetrievalStrategy {
  key: 'dense' | 'bm25' | 'hybrid'
  label: string
  /** CSS custom property holding this strategy's categorical colour. */
  colorVar: string
  description: string
  recallAt10: Metric
  ndcgAt10: Metric
}

/**
 * Colour follows the entity, not the rank. Dense is always blue, BM25 always
 * orange, hybrid always aqua — on every chart, in every mode, whether or not
 * the bar has a value. Re-colouring survivors when a filter changes the series
 * count is one of the fastest ways to make a dashboard lie.
 */
export const retrievalStrategies: RetrievalStrategy[] = [
  {
    key: 'dense',
    label: 'Dense only',
    colorVar: '--series-1',
    description: 'pgvector HNSW cosine over text-embedding-3-small, top 50 → 10',
    recallAt10: measured(
      0.9583,
      'Session 49 — 120 held-out queries, 6,041 embedded chunks',
      '2026-08-11',
      'python scripts/benchmark_hybrid_retrieval.py',
    ),
    ndcgAt10: measured(
      0.8310,
      'Session 49 — 120 held-out queries, 6,041 embedded chunks',
      '2026-08-11',
      'python scripts/benchmark_hybrid_retrieval.py',
    ),
  },
  {
    key: 'bm25',
    label: 'BM25 only',
    colorVar: '--series-2',
    description: 'Elasticsearch lexical search over llm_eval_chunks, top 50 → 10',
    recallAt10: measured(
      0.9417,
      'Session 49 — 120 held-out queries, 6,041 indexed chunks',
      '2026-08-11',
      'python scripts/benchmark_hybrid_retrieval.py',
    ),
    ndcgAt10: measured(
      0.8808,
      'Session 49 — 120 held-out queries, 6,041 indexed chunks',
      '2026-08-11',
      'python scripts/benchmark_hybrid_retrieval.py',
    ),
  },
  {
    key: 'hybrid',
    label: 'Hybrid RRF',
    colorVar: '--series-3',
    description: 'Reciprocal rank fusion of dense + BM25, k=60, final top 10',
    recallAt10: measured(
      0.9833,
      'SQuAD v2 — dense and BM25 are complementary here, so fusion beats both',
      '2026-08-11',
      'python scripts/benchmark_hybrid_retrieval.py',
    ),
    ndcgAt10: measured(
      0.8991,
      'SQuAD v2 — dense and BM25 are complementary here, so fusion beats both',
      '2026-08-11',
      'python scripts/benchmark_hybrid_retrieval.py',
    ),
  },
]

/** Configured inputs. These are settings, not results — never chart them. */
export const retrievalConfig = {
  embeddingModel: 'text-embedding-3-small',
  embeddingDimensions: 1536,
  vectorIndex: 'pgvector HNSW (cosine)',
  denseTopK: 50,
  bm25TopK: 50,
  rrfK: 60,
  finalTopK: 10,
  generationContextChunks: 4,
  generationContextTokens: 2000,
}

/* ------------------------------------------------------------------ */
/* Candidate generation                                                */
/* ------------------------------------------------------------------ */

export interface ProviderCoverage {
  provider: string
  model: string
  /** Real API generations count toward provider-diversity claims; mocks do not. */
  countsAsRealDiversity: boolean
  persistedAnswers: Metric
  note: string
}

export const providerCoverage: ProviderCoverage[] = [
  {
    provider: 'Mock',
    model: 'mock-provider-v0',
    countsAsRealDiversity: false,
    persistedAnswers: measured(
      849,
      'Sum of runs/local_mock_*_candidate_answers.jsonl line counts',
      '2026-08-05',
      'for f in runs/*_candidate_answers.jsonl; do wc -l < "$f"; done',
    ),
    note: 'Rehearsal only. Proves the pipeline, proves nothing about answer quality.',
  },
  {
    provider: 'OpenAI',
    model: 'gpt-4o-mini',
    countsAsRealDiversity: true,
    persistedAnswers: measured(
      120,
      'cgen__dual_judge_slice_v1__openai__* on golden_squad_v2_sampled',
      '2026-08-12',
      'python scripts/generate_candidates_for_dataset.py --provider openai --allow-paid-api',
    ),
    note: 'Real API calls, zero failures.',
  },
  {
    provider: 'Anthropic',
    model: 'claude-haiku-4-5',
    countsAsRealDiversity: true,
    persistedAnswers: measured(
      120,
      'cgen__dual_judge_slice_v1__anthropic__* on golden_squad_v2_sampled',
      '2026-08-12',
      'python scripts/generate_candidates_for_dataset.py --provider anthropic --allow-paid-api',
    ),
    note: 'Real API calls, zero failures. Correctly abstained on 20 of 40 unanswerable questions.',
  },
  {
    provider: 'Self-hosted',
    model: 'mistral-7b-instruct-v0.3-awq (vLLM on AWS T4)',
    countsAsRealDiversity: true,
    persistedAnswers: measured(
      1080,
      '9 configs: 3 retrieval modes x 3 prompt versions, 120 cases each',
      '2026-08-12',
      'python scripts/generate_candidates_for_dataset.py --provider self-hosted --concurrency 12',
    ),
    note: 'Reported separately from API coverage — a different claim.',
  },
]

export const generation = {
  full120CaseRuns: measured(
    11,
    'Run configurations on golden_squad_v2_sampled, 120 cases each',
    '2026-08-12',
  ),
  full120CaseRunsWithRealProviders: measured(
    11,
    'All 11 used a real provider; mock output never enters a measured run',
    '2026-08-12',
  ),
  totalCandidateAnswers: measured(
    1320,
    'All completed, zero generation failures',
    '2026-08-12',
  ),
  targetFull120CaseRuns: 67,
} satisfies Record<string, Metric | number>

/* ------------------------------------------------------------------ */
/* Judging                                                             */
/* ------------------------------------------------------------------ */

export const judging = {
  validationSliceSize: measured(
    120,
    'Session 33 — held-out slice built from retrieval_heldout_120_v0.2.jsonl',
    '2026-08-06',
    'python scripts/rehearse_judge_validation.py --limit 120',
  ),
  gpt4oMiniScoresPersisted: measured(
    3,
    'runs/local_mock_20260802_063757_gpt4o_mini_judge_scores.jsonl',
    '2026-08-02',
    'python scripts/gpt4o_mini_judge_answers.py <file> --limit 3',
  ),
  ruleBasedScoresPersisted: measured(
    120,
    'runs/local_mock_20260730_054734_rule_based_judge_scores.jsonl',
    '2026-07-30',
    'python scripts/rule_based_judge_answers.py <file>',
  ),
  bulkJudgedAnswers: measured(
    1320,
    'Self-hosted Mistral-7B on AWS T4, concurrency 16, zero failed scores',
    '2026-08-12',
    'python scripts/bulk_self_hosted_judge_answers.py',
  ),
  passFailAgreement: measured(
    0.65,
    'gpt-4.1-mini vs self-hosted 7B on the same 120-answer SQuAD slice',
    '2026-08-12',
    'python scripts/dual_judge_validate.py --judge-a-model gpt-4.1-mini',
  ),
  cohensKappa: measured(
    0.264,
    'Chance-adjusted; "fair" agreement at best. Judge A pass rate 0.867, judge B 0.533',
    '2026-08-12',
    'python scripts/recompute_validation_report.py runs/dual_judge_squad/real_7b_report.json',
  ),
  manualReviewRoutingRate: measured(
    0.433,
    '52 of 120 cases routed by the disagreement threshold',
    '2026-08-12',
  ),
  targetAgreement: 0.84,
  targetBulkJudged: 8000,
} satisfies Record<string, Metric | number>

/* ------------------------------------------------------------------ */
/* Serving & infrastructure                                            */
/* ------------------------------------------------------------------ */

export const infrastructure = {
  traceSpanDocuments: measured(
    6219,
    'Emitted as a byproduct of real generation and judging, not a loop',
    '2026-08-12',
    'python scripts/count_trace_documents.py',
  ),
  uniqueTraces: measured(
    3948,
    'One trace produces many span documents — counted separately, never conflated',
    '2026-08-12',
    'python scripts/count_trace_documents.py',
  ),
  instrumentedServiceLayers: measured(
    6,
    'Session 35 — gateway, retrieval, provider, judge, tool, storage spans asserted by tests',
    '2026-08-04',
    'python -m pytest tests/test_eval_worker_tracing.py',
  ),
  vllmThroughputTokensPerSecond: measured(
    60.43,
    'Measured on the judging workload itself at concurrency 16, not a synthetic benchmark. 871.15 total tok/s; the workload is prefill-bound at 13.4:1',
    '2026-08-12',
    'python scripts/bulk_self_hosted_judge_answers.py',
  ),
  judgedPerMinute: measured(
    36.04,
    '1,320 answers in 36.6 minutes on a single T4',
    '2026-08-12',
  ),
  costPerThousandJudgements: measured(
    0.2433,
    'g4dn.xlarge on-demand at $0.526/h',
    '2026-08-12',
  ),
  targetThroughput: 145,
  benchmarkConcurrency: 16,
  targetTraceDocuments: 10000,
} satisfies Record<string, Metric | number>

export const ci = {
  // The gate LOGIC is verified locally: it exits 1 on a deliberate regression and
  // 8 tests cover it. Whether GitHub Actions has actually executed the workflow is
  // a separate fact, and claiming the gate "blocks" changes before a remote run has
  // happened would be the same overclaim this dashboard exists to prevent.
  regressionGateLogic: measured(
    1,
    'compare_regression_metrics.py exits 1 on a deliberate regression; 8 gate tests pass',
    '2026-08-12',
    'python scripts/compare_regression_metrics.py --baseline runs/test_regression_gate/failing_baseline.json --current runs/test_regression_gate/failing_current.json',
  ),
  regressionGateExecutedInCi: notMeasured(
    'The workflow is committed and triggers on push to main, but no completed GitHub Actions run has been observed from here.',
    'private repository; run status not readable without the GitHub API',
    'open the Actions tab after a push to a watched path',
  ),
  evalScoreRegressionThreshold: 0.05,
  latencyCostRegressionThreshold: 0.15,
}

/** Where the runs table gets its data — currently a hardcoded dict. */
export const runsEndpointProvenance = placeholder(
  0,
  'backend/main.py EVAL_RUNS — an in-memory dict, not a database',
  'GET /eval-runs returns one hand-written row with total_cases=3, passed_cases=2. Session 12 flagged these as placeholder API data.',
)
