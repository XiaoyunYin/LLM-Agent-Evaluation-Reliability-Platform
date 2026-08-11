import { useCallback, useState } from 'react'
import { api } from '../api/client'
import { describeError, useApi } from '../hooks/useApi'
import { Callout, Panel } from '../components/Panel'
import { StatusPill } from '../components/StatusPill'
import { EmptyState, ErrorState, LoadingRows } from '../components/states'
import type { ReviewCase, ReviewStatus } from '../types/api'

const STATUSES: ReviewStatus[] = ['pending', 'reviewed', 'resolved']

function empty(value: string | null) {
  return value ?? 'unset'
}

function scoreDelta(c: ReviewCase) {
  return Math.abs(c.judge_a_score - c.judge_b_score)
}

export function ReviewQueuePage() {
  const fetcher = useCallback((signal: AbortSignal) => api.listReviewCases(signal), [])
  const cases = useApi(fetcher, [])

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [local, setLocal] = useState<Record<string, ReviewCase>>({})

  const rows: ReviewCase[] =
    cases.status === 'success' ? cases.data.map((c) => local[c.id] ?? c) : []

  const selected = rows.find((c) => c.id === selectedId) ?? null

  async function withBusy(id: string, work: () => Promise<ReviewCase>) {
    setBusyId(id)
    setError(null)
    try {
      const updated = await work()
      setLocal((prev) => ({ ...prev, [updated.id]: updated }))
    } catch (err) {
      setError(describeError(err).error)
    } finally {
      setBusyId(null)
    }
  }

  const decide = (c: ReviewCase, humanLabel: string, finalDecision: string) =>
    withBusy(c.id, () =>
      api.updateReviewDecision(c.id, {
        human_label: humanLabel,
        final_decision: finalDecision,
      }),
    )

  const setStatus = (c: ReviewCase, status: ReviewStatus) =>
    withBusy(c.id, () => api.updateReviewStatus(c.id, status))

  return (
    <>
      <Callout glyph="i">
        <strong>Review routing is a safety workflow, not an accuracy metric.</strong>{' '}
        The queue contains cases where judges split on pass/fail or their scores
        differ enough to need a human decision.
      </Callout>

      <Panel
        title="Manual review queue"
        description="Rows come from GET /review-cases, which now includes saved manual-review JSONL artifacts."
        actions={
          cases.status === 'success' ? (
            <button className="btn btn--sm" onClick={cases.refetch}>
              Refresh
            </button>
          ) : null
        }
        flush
      >
        {cases.status === 'loading' || cases.status === 'idle' ? (
          <LoadingRows cols={7} />
        ) : cases.status === 'error' ? (
          <ErrorState
            error={cases.error}
            kind={cases.kind}
            httpStatus={cases.httpStatus}
            onRetry={cases.refetch}
          />
        ) : rows.length === 0 ? (
          <EmptyState
            title="Queue is empty"
            body="No saved disagreement cases were returned by the backend."
          />
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Case ID</th>
                  <th>Run ID</th>
                  <th>Judge disagreement</th>
                  <th>Human label</th>
                  <th>Final decision</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c.id}>
                    <td className="mono">{c.case_id}</td>
                    <td className="mono muted">{c.run_id}</td>
                    <td>
                      {c.disagreement_reason}
                      <div className="muted">
                        score delta {scoreDelta(c).toFixed(2)}
                      </div>
                    </td>
                    <td className={c.human_label ? undefined : 'absent'}>
                      {empty(c.human_label)}
                    </td>
                    <td className={c.final_decision ? undefined : 'absent'}>
                      {empty(c.final_decision)}
                    </td>
                    <td>
                      <StatusPill value={c.status} kind="review" />
                    </td>
                    <td className="num">
                      <button
                        className="btn btn--sm"
                        onClick={() =>
                          setSelectedId(selectedId === c.id ? null : c.id)
                        }
                        aria-expanded={selectedId === c.id}
                      >
                        {selectedId === c.id ? 'Close' : 'Review'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {selected ? (
        <Panel
          title={`Review ${selected.case_id}`}
          description="Use the answer, judge scores, and disagreement reason together before recording a human label."
          actions={<StatusPill value={selected.status} kind="review" />}
        >
          <div className="stack">
            <div>
              <div className="nav__label" style={{ padding: 0 }}>
                Candidate answer
              </div>
              <p className="note" style={{ marginTop: 6 }}>
                {selected.answer}
              </p>
            </div>

            <dl className="kv">
              <dt>Run ID</dt>
              <dd className="mono">{selected.run_id}</dd>
              <dt>Judge A score</dt>
              <dd>{selected.judge_a_score.toFixed(2)}</dd>
              <dt>Judge B score</dt>
              <dd>{selected.judge_b_score.toFixed(2)}</dd>
              <dt>Score delta</dt>
              <dd>{scoreDelta(selected).toFixed(2)}</dd>
              <dt>Judge disagreement</dt>
              <dd>{selected.disagreement_reason}</dd>
              <dt>Human label</dt>
              <dd className={selected.human_label ? undefined : 'absent'}>
                {empty(selected.human_label)}
              </dd>
              <dt>Final decision</dt>
              <dd className={selected.final_decision ? undefined : 'absent'}>
                {empty(selected.final_decision)}
              </dd>
            </dl>

            <div>
              <div className="nav__label" style={{ padding: '0 0 6px' }}>
                Decision
              </div>
              <div className="row">
                <button
                  className="btn"
                  disabled={busyId === selected.id}
                  onClick={() => decide(selected, 'correct', 'accept')}
                >
                  Correct - accept
                </button>
                <button
                  className="btn"
                  disabled={busyId === selected.id}
                  onClick={() => decide(selected, 'incorrect', 'reject')}
                >
                  Incorrect - reject
                </button>
                <button
                  className="btn"
                  disabled={busyId === selected.id}
                  onClick={() => decide(selected, 'ambiguous', 'escalate')}
                >
                  Ambiguous - escalate
                </button>
              </div>
            </div>

            <div>
              <div className="nav__label" style={{ padding: '0 0 6px' }}>
                Workflow status
              </div>
              <div className="row">
                {STATUSES.map((status) => (
                  <button
                    key={status}
                    className={`btn${selected.status === status ? ' btn--primary' : ''}`}
                    disabled={busyId === selected.id || selected.status === status}
                    onClick={() => setStatus(selected, status)}
                  >
                    {status}
                  </button>
                ))}
              </div>
              <p className="bars__footnote">
                Decision and status answer different questions: what the human
                concluded, and where the case sits in the workflow.
              </p>
            </div>

            {error ? (
              <Callout tone="warn" glyph="!">
                {error}
              </Callout>
            ) : null}
          </div>
        </Panel>
      ) : null}
    </>
  )
}
