/**
 * The only place in the app that calls fetch().
 *
 * Everything goes through `request()`, which does three jobs the rest of the
 * codebase should never repeat:
 *
 *  1. Turns a non-2xx response into a thrown ApiError. `fetch` does NOT reject
 *     on 404 or 500 — it resolves with ok:false. Code that forgets this
 *     happily renders an error body as if it were data.
 *  2. Attaches an AbortSignal so a component that unmounts mid-flight cannot
 *     write into a dead component.
 *  3. Pulls FastAPI's `detail` field out of the error body, so a 404 shows
 *     "Eval run not found" instead of "Request failed".
 */

import type {
  CreateRunRequest,
  EvalRunSummary,
  HealthResponse,
  MetricsSummaryResponse,
  ReviewCase,
  ReviewDecisionUpdate,
  ReviewStatus,
  RunResponse,
} from '../types/api'

/**
 * Dev: Vite proxies /api → http://127.0.0.1:8000 (see vite.config.ts), so the
 * browser only ever talks to its own origin and CORS never enters the picture.
 * Prod: set VITE_API_BASE_URL at build time to the real backend origin.
 */
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api'

// Fields are declared and assigned explicitly rather than using TypeScript's
// constructor parameter properties: this tsconfig sets `erasableSyntaxOnly`,
// which bans syntax that cannot be removed by simply stripping types. Parameter
// properties emit real assignment code, so they are not erasable.
export class ApiError extends Error {
  readonly status: number
  readonly url: string

  constructor(message: string, status: number, url: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.url = url
  }
}

/** Raised when the backend is not running at all — a different UX from a 500. */
export class NetworkError extends Error {
  readonly url: string

  constructor(url: string, cause?: unknown) {
    super('Could not reach the backend.')
    this.name = 'NetworkError'
    this.url = url
    this.cause = cause
  }
}

async function request<T>(
  path: string,
  init?: RequestInit & { signal?: AbortSignal },
): Promise<T> {
  const url = `${BASE_URL}${path}`

  let response: Response
  try {
    response = await fetch(url, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        ...(init?.headers ?? {}),
      },
    })
  } catch (cause) {
    // fetch only rejects for network-level failures: server down, DNS, CORS,
    // or an aborted request. Re-throw aborts untouched so the hook can ignore
    // them rather than painting an error.
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause
    throw new NetworkError(url, cause)
  }

  if (!response.ok) {
    // A dead backend behind the Vite dev proxy does NOT surface as a fetch
    // rejection — the proxy itself is alive and answers 502. Verified by
    // stopping uvicorn and curling /api/health. Without this branch the UI
    // says "Request failed (502)", which sends you hunting through FastAPI
    // logs that do not exist because FastAPI is not running.
    if (response.status === 502 || response.status === 503 || response.status === 504) {
      throw new NetworkError(url)
    }

    let detail = `${response.status} ${response.statusText}`
    try {
      const body = (await response.json()) as { detail?: string }
      if (body?.detail) detail = body.detail
    } catch {
      // Body was not JSON. Keep the status-line message.
    }
    throw new ApiError(detail, response.status, url)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const api = {
  health: (signal?: AbortSignal) =>
    request<HealthResponse>('/health', { signal }),

  listEvalRuns: (signal?: AbortSignal) =>
    request<EvalRunSummary[]>('/eval-runs', { signal }),

  getMetricsSummary: (signal?: AbortSignal) =>
    request<MetricsSummaryResponse>('/metrics-summary', { signal }),

  getRun: (runId: string, signal?: AbortSignal) =>
    request<RunResponse>(`/runs/${encodeURIComponent(runId)}`, { signal }),

  createRun: (body: CreateRunRequest, signal?: AbortSignal) =>
    request<RunResponse>('/runs', {
      method: 'POST',
      body: JSON.stringify(body),
      signal,
    }),

  listReviewCases: (signal?: AbortSignal) =>
    request<ReviewCase[]>('/review-cases', { signal }),

  updateReviewDecision: (
    id: string,
    body: ReviewDecisionUpdate,
    signal?: AbortSignal,
  ) =>
    request<ReviewCase>(`/review-cases/${encodeURIComponent(id)}/decision`, {
      method: 'PATCH',
      body: JSON.stringify(body),
      signal,
    }),

  updateReviewStatus: (id: string, status: ReviewStatus, signal?: AbortSignal) =>
    request<ReviewCase>(`/review-cases/${encodeURIComponent(id)}/status`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
      signal,
    }),
}
