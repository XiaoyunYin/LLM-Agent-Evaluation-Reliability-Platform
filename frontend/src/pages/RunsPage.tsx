import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { describeError, useApi } from '../hooks/useApi'
import { Callout, Panel } from '../components/Panel'
import { StatusPill } from '../components/StatusPill'
import { EmptyState, ErrorState, LoadingRows } from '../components/states'
import { ProvenanceBadge } from '../components/ProvenanceBadge'
import { runsEndpointProvenance } from '../data/metricsSnapshot'
import type { EvalRunSummary, RunResponse } from '../types/api'

const TERMINAL = new Set(['completed', 'failed'])
const POLL_MS = 2000

function formatScore(score: number | null) {
  if (score === null) return 'Not measured'
  return `${(score * 100).toFixed(1)}%`
}

function formatLatency(latencyMs: number | null) {
  if (latencyMs === null) return 'Not measured'
  if (latencyMs >= 1000) return `${(latencyMs / 1000).toFixed(2)}s`
  return `${Math.round(latencyMs)}ms`
}

function formatCreated(value: string | null | undefined) {
  if (!value) return 'Unknown'
  return new Date(value).toLocaleString()
}

function metricClass(value: number | null) {
  return value === null ? 'num absent' : 'num'
}

function RunsTable({ runs }: { runs: EvalRunSummary[] }) {
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>Run ID</th>
            <th>Dataset</th>
            <th>Provider</th>
            <th className="num">Score</th>
            <th className="num">Latency</th>
            <th>Created</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.run_id}>
              <td className="mono">{run.run_id}</td>
              <td>{run.dataset_version}</td>
              <td>{run.provider_name}</td>
              <td
                className={metricClass(run.score)}
                title={run.score === null ? 'No measured eval score is stored yet.' : undefined}
              >
                {formatScore(run.score)}
              </td>
              <td
                className={metricClass(run.latency_ms)}
                title={
                  run.latency_ms === null
                    ? 'No measured end-to-end latency is stored yet.'
                    : undefined
                }
              >
                {formatLatency(run.latency_ms)}
              </td>
              <td className="mono muted">{formatCreated(run.created_at)}</td>
              <td>
                <StatusPill value={run.status} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function RunsPage() {
  const listFetcher = useCallback((signal: AbortSignal) => api.listEvalRuns(signal), [])
  const evalRuns = useApi(listFetcher, [])

  const [tracked, setTracked] = useState<RunResponse[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<React.ReactNode>(null)
  const [datasetVersion, setDatasetVersion] = useState('golden_rag_v0.1')
  const [providerName, setProviderName] = useState('mock')

  async function createRun(event: React.FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setSubmitError(null)

    try {
      const run = await api.createRun({
        dataset_version: datasetVersion,
        provider_name: providerName,
      })
      setTracked((prev) => [run, ...prev.filter((r) => r.run_id !== run.run_id)])
    } catch (error) {
      const described = describeError(error)
      setSubmitError(
        described.httpStatus === 500 ? (
          <>
            <strong>{described.error}</strong> - this endpoint writes the run to
            Redis before responding, so the usual cause is that Redis is not
            running. Start it with <code>docker compose up -d redis</code>, then
            start the worker with{' '}
            <code>.\.venv\Scripts\python.exe scripts\run_eval_worker.py</code>.
          </>
        ) : (
          described.error
        ),
      )
    } finally {
      setSubmitting(false)
    }
  }

  const trackedRef = useRef(tracked)
  trackedRef.current = tracked
  const pending = tracked.filter((r) => !TERMINAL.has(r.status))

  useEffect(() => {
    if (pending.length === 0) return
    const controller = new AbortController()

    const id = setInterval(async () => {
      const active = trackedRef.current.filter((r) => !TERMINAL.has(r.status))
      const updates = await Promise.allSettled(
        active.map((r) => api.getRun(r.run_id, controller.signal)),
      )
      if (controller.signal.aborted) return

      const fresh = new Map<string, RunResponse>()
      for (const result of updates) {
        if (result.status === 'fulfilled') fresh.set(result.value.run_id, result.value)
      }
      if (fresh.size === 0) return
      setTracked((prev) => prev.map((r) => fresh.get(r.run_id) ?? r))
    }, POLL_MS)

    return () => {
      controller.abort()
      clearInterval(id)
    }
  }, [pending.length])

  return (
    <>
      <Panel
        title="Queue an eval run"
        description="POST /runs writes the run to Redis with status=queued and enqueues a job. The worker moves it from queued to running to completed."
      >
        <form className="row" onSubmit={createRun}>
          <div className="field">
            <label htmlFor="dataset">Dataset version</label>
            <select
              id="dataset"
              value={datasetVersion}
              onChange={(e) => setDatasetVersion(e.target.value)}
            >
              <option value="golden_rag_v0.1">golden_rag_v0.1</option>
              <option value="golden_agentic_tools_v0.1">
                golden_agentic_tools_v0.1
              </option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="provider">Provider</label>
            <select
              id="provider"
              value={providerName}
              onChange={(e) => setProviderName(e.target.value)}
            >
              <option value="mock">mock</option>
              <option value="openai">openai</option>
              <option value="anthropic">anthropic</option>
              <option value="self-hosted">self-hosted</option>
            </select>
          </div>
          <button className="btn btn--primary" type="submit" disabled={submitting}>
            {submitting ? 'Queueing...' : 'Queue run'}
          </button>
        </form>

        {submitError ? (
          <div style={{ marginTop: 12 }}>
            <Callout tone="warn" glyph="!">
              {submitError}
            </Callout>
          </div>
        ) : null}

        <p className="bars__footnote">
          Selecting <code>openai</code> or <code>anthropic</code> only records the
          provider name on the run. The current worker still executes a
          placeholder pipeline, so no real API call is made and no candidate
          answers are persisted.
        </p>
      </Panel>

      <Panel
        title="Runs queued from this session"
        description={
          pending.length > 0
            ? `Polling ${pending.length} run${pending.length === 1 ? '' : 's'} every ${POLL_MS / 1000}s until terminal.`
            : 'Live status from GET /runs/{run_id}, backed by Redis.'
        }
        flush
      >
        {tracked.length === 0 ? (
          <EmptyState
            title="Nothing queued yet"
            body="Queue a run above. If the worker is not running, the status will stay at queued."
          />
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Run ID</th>
                  <th>Dataset</th>
                  <th>Provider</th>
                  <th>Status</th>
                  <th>Started</th>
                </tr>
              </thead>
              <tbody>
                {tracked.map((run) => (
                  <tr key={run.run_id}>
                    <td className="mono">{run.run_id}</td>
                    <td>{run.dataset_version}</td>
                    <td>{run.provider_name}</td>
                    <td>
                      <StatusPill value={run.status} />
                    </td>
                    <td className="mono muted">
                      {run.started_at
                        ? new Date(run.started_at).toLocaleTimeString()
                        : 'Unknown'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel
        title="Eval run list"
        description={runsEndpointProvenance.note}
        actions={<ProvenanceBadge status="placeholder" />}
        flush
      >
        {evalRuns.status === 'loading' || evalRuns.status === 'idle' ? (
          <LoadingRows cols={7} />
        ) : evalRuns.status === 'error' ? (
          <ErrorState
            error={evalRuns.error}
            kind={evalRuns.kind}
            httpStatus={evalRuns.httpStatus}
            onRetry={evalRuns.refetch}
          />
        ) : evalRuns.data.length === 0 ? (
          <EmptyState
            title="No eval runs"
            body="The endpoint responded successfully with an empty list."
          />
        ) : (
          <RunsTable runs={evalRuns.data} />
        )}
        <div style={{ padding: '14px 18px' }}>
          <p className="note">
            <strong>Score</strong> and <strong>Latency</strong> stay marked as
            not measured until the backend persists real judge scores and
            end-to-end timings. The table is allowed to show missing metrics;
            it is not allowed to make them up.
          </p>
        </div>
      </Panel>
    </>
  )
}
