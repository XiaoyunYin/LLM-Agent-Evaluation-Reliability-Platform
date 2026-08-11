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
    1100,
    'Session 19 — datasets/corpus/raw, verified by file count',
    '2026-08-05',
    'ls datasets/corpus/raw | wc -l',
  ),
  chunks: measured(
    6041,
    'Session 48 — datasets/corpus/chunks.jsonl line count after corpus regeneration',
    '2026-08-11',
    'wc -l < datasets/corpus/chunks.jsonl',
  ),
  distinctChunkTexts: measured(
    6041,
    'Session 48 — every chunk text is unique; duplication factor 1.00x',
    '2026-08-11',
    'python scripts/analyze_corpus_duplication.py',
  ),
  chunksIndexedInElasticsearch: measured(
    6041,
    'Session 48 — scripts/index_chunks_to_elasticsearch.py',
    '2026-08-11',
    'python scripts/index_chunks_to_elasticsearch.py',
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
      0.2212,
      'Session 49 — 120 held-out queries, 6,041 embedded chunks',
      '2026-08-11',
      'python scripts/benchmark_hybrid_retrieval.py',
    ),
    ndcgAt10: measured(
      0.2109,
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
      0.3505,
      'Session 49 — 120 held-out queries, 6,041 indexed chunks',
      '2026-08-11',
      'python scripts/benchmark_hybrid_retrieval.py',
    ),
    ndcgAt10: measured(
      0.3077,
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
      0.2832,
      'Session 49 — fusing a near-uninformative dense ranking lowers BM25',
      '2026-08-11',
      'python scripts/benchmark_hybrid_retrieval.py',
    ),
    ndcgAt10: measured(
      0.2936,
      'Session 49 — fusing a near-uninformative dense ranking lowers BM25',
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
    model: 'configured, never invoked for generation',
    countsAsRealDiversity: true,
    persistedAnswers: notMeasured(
      'OpenAIProvider exists and is wired to the CLI, but no run has persisted real answers.',
      'no OpenAI candidate-generation run has been executed',
      'python scripts/mock_generate_answers.py --provider openai',
    ),
    note: 'Provider plumbing landed in Session 8; a real run is still outstanding.',
  },
  {
    provider: 'Anthropic',
    model: 'configured, never invoked for generation',
    countsAsRealDiversity: true,
    persistedAnswers: notMeasured(
      'AnthropicProvider exists and is wired to the CLI, but no run has persisted real answers.',
      'no Anthropic candidate-generation run has been executed',
      'python scripts/mock_generate_answers.py --provider anthropic',
    ),
    note: 'Provider plumbing landed in Session 9; a real run is still outstanding.',
  },
  {
    provider: 'Self-hosted',
    model: 'optional — not required by the current headline claims',
    countsAsRealDiversity: false,
    persistedAnswers: notMeasured(
      'Optional interface. Self-hosted candidate generation is explicitly out of scope.',
      'not attempted by design',
    ),
    note: 'The required self-hosted work is the bulk JUDGE, not candidate generation.',
  },
]

export const generation = {
  full120CaseRuns: measured(
    7,
    'runs/*_candidate_answers.jsonl files containing exactly 120 rows',
    '2026-08-05',
  ),
  full120CaseRunsWithRealProviders: measured(
    0,
    'No candidate-answer file was produced by a real OpenAI or Anthropic call',
    '2026-08-05',
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
  bulkJudgedAnswers: notMeasured(
    'The self-hosted 7B judge carries bulk judging and has never run against real hardware.',
    'no vLLM / Mistral-7B-Instruct-v0.3-AWQ GPU window yet',
    'swap SELF_HOSTED_JUDGE_URL to the real vLLM endpoint, then run the bulk judge',
  ),
  passFailAgreement: notMeasured(
    'The 0.00% from Session 33 came from a deterministic stand-in judge vs a mock 7B endpoint. It measures the harness, not the judges.',
    'requires GPT-4o-mini and the real self-hosted 7B judge on the same 120-answer slice',
    'python scripts/dual_judge_validate.py --use-gpt4o-mini',
  ),
  cohensKappa: notMeasured(
    'Same blocker as agreement — kappa over mock judges is not a judge-quality number.',
    'requires both real judges on the same slice',
  ),
  manualReviewRoutingRate: notMeasured(
    'The Session 33 rehearsal routed 120/120 cases because the mock judge disagreed with everything.',
    'requires both real judges on the same slice',
  ),
  targetAgreement: 0.84,
  targetBulkJudged: 8000,
} satisfies Record<string, Metric | number>

/* ------------------------------------------------------------------ */
/* Serving & infrastructure                                            */
/* ------------------------------------------------------------------ */

export const infrastructure = {
  traceSpanDocuments: notMeasured(
    'The OTLP → Collector → Elasticsearch path is configured and config-validated, but no span has been counted in Elasticsearch.',
    'Docker was not running during Session 36',
    'docker compose up -d elasticsearch otel-collector; python scripts/emit_trace_smoke.py; python scripts/count_trace_documents.py',
  ),
  uniqueTraces: notMeasured(
    'One trace produces many span documents — these must be counted separately, never conflated.',
    'Docker was not running during Session 36',
    'python scripts/count_trace_documents.py',
  ),
  instrumentedServiceLayers: measured(
    6,
    'Session 35 — gateway, retrieval, provider, judge, tool, storage spans asserted by tests',
    '2026-08-04',
    'python -m pytest tests/test_eval_worker_tracing.py',
  ),
  vllmThroughputTokensPerSecond: notMeasured(
    'No GPU has been rented. Throughput must be benchmarked at concurrency 16 on g4dn.xlarge / T4.',
    'no GPU window yet',
  ),
  targetThroughput: 145,
  benchmarkConcurrency: 16,
  targetTraceDocuments: 10000,
} satisfies Record<string, Metric | number>

export const ci = {
  regressionGate: notMeasured(
    'There is no .github/workflows directory. Nothing currently blocks a regression.',
    'CI pipeline not built',
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
