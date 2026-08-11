/**
 * Wire types for the FastAPI backend.
 *
 * These mirror the Pydantic models in backend/main.py. They are hand-written
 * rather than generated, which means they can drift — the backend exposes an
 * OpenAPI schema at /openapi.json, so a later session can generate these
 * instead and delete the drift risk.
 */

export interface HealthResponse {
  status: string
}

export type DashboardMetricStatus = 'measured' | 'non_final' | 'not_measured'
export type DashboardMetricUnit = 'count' | 'percentage' | 'ratio'

export interface DashboardMetric {
  key: string
  label: string
  value: number | null
  unit: DashboardMetricUnit
  status: DashboardMetricStatus
  source: string | null
  measured_at: string | null
  command: string | null
  note: string
}

export interface MetricsSummaryResponse {
  metrics: DashboardMetric[]
}

/**
 * GET /eval-runs — served from the in-memory EVAL_RUNS dict in
 * backend/main.py. total_cases / passed_cases are hardcoded placeholders
 * (build log, Session 12), which is why the UI renders this table behind a
 * placeholder banner.
 */
export interface EvalRunSummary {
  run_id: string
  dataset_version: string
  provider_name: string
  status: string
  created_at: string | null
  score: number | null
  latency_ms: number | null
  total_cases?: number
  passed_cases?: number
}

/** POST /runs and GET /runs/{id} — the Redis-backed orchestration path. */
export interface RunResponse {
  run_id: string
  dataset_version: string
  provider_name: string
  status: string
  started_at: string | null
  model_name?: string | null
  task_family?: string | null
  retrieval_mode?: string | null
  prompt_version?: string | null
  repeat_id?: string | null
  matrix_id?: string | null
}

export interface CreateRunRequest {
  run_id?: string
  dataset_version: string
  provider_name: string
  model_name?: string | null
  task_family?: string
  retrieval_mode?: string
  prompt_version?: string
  repeat_id?: string
  matrix_id?: string
  expected_case_count?: number | null
}

export type ReviewStatus = 'pending' | 'reviewed' | 'resolved'

/** GET /review-cases — also in-memory today. */
export interface ReviewCase {
  id: string
  run_id: string
  case_id: string
  disagreement_reason: string
  answer: string
  judge_a_score: number
  judge_b_score: number
  human_label: string | null
  final_decision: string | null
  status: ReviewStatus
}

export interface ReviewDecisionUpdate {
  human_label: string
  final_decision: string
}
