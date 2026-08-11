import { useCallback } from 'react'
import { api } from '../api/client'
import { Callout, Panel } from '../components/Panel'
import { StatTile } from '../components/StatTile'
import { ErrorState, LoadingRows } from '../components/states'
import { useApi } from '../hooks/useApi'
import type { DashboardMetric } from '../types/api'
import type { Metric } from '../types/provenance'

const METRIC_ORDER = [
  'recall_at_10',
  'ndcg_at_10',
  'judge_agreement_percentage',
  'disagreement_percentage',
  'judged_answer_count',
  'eval_run_count',
  'trace_count',
]

const HEADLINE_METRICS = new Set([
  'recall_at_10',
  'judge_agreement_percentage',
  'judged_answer_count',
])

function toTileMetric(metric: DashboardMetric): Metric<number> {
  if (metric.status === 'not_measured' || metric.value === null) {
    return {
      status: 'not_measured',
      note: metric.note,
      command: metric.command ?? undefined,
    }
  }

  if (metric.status === 'non_final') {
    return {
      status: 'non_final',
      value: metric.value,
      source: metric.source ?? 'saved artifact',
      measuredAt: metric.measured_at ?? undefined,
      command: metric.command ?? undefined,
      note: metric.note,
    }
  }

  return {
    status: 'measured',
    value: metric.value,
    source: metric.source ?? 'backend API',
    measuredAt: metric.measured_at ?? 'unknown',
    command: metric.command ?? undefined,
  }
}

function formatMetric(metric: DashboardMetric) {
  if (metric.unit === 'percentage') return (value: number) => value.toFixed(1)
  if (metric.unit === 'ratio') return (value: number) => value.toFixed(4)
  return (value: number) => value.toLocaleString()
}

function unit(metric: DashboardMetric) {
  return metric.unit === 'percentage' ? '%' : undefined
}

function sourceText(metric: DashboardMetric) {
  if (metric.status === 'not_measured') return metric.note
  return metric.source ? `${metric.source} - ${metric.note}` : metric.note
}

export function OverviewPage() {
  const fetcher = useCallback((signal: AbortSignal) => api.getMetricsSummary(signal), [])
  const metrics = useApi(fetcher, [])

  const ordered =
    metrics.status === 'success'
      ? METRIC_ORDER.map((key) => metrics.data.metrics.find((m) => m.key === key)).filter(
          (m): m is DashboardMetric => Boolean(m),
        )
      : []

  const headlineMetrics = ordered.filter((metric) =>
    HEADLINE_METRICS.has(metric.key),
  )
  const supportingMetrics = ordered.filter(
    (metric) => !HEADLINE_METRICS.has(metric.key),
  )

  return (
    <>
      <Callout glyph="i">
        <strong>Dashboard rule:</strong> numbers come from saved artifacts or the
        backend API. Missing values stay missing, and mock rehearsal values are
        labeled non-final.
      </Callout>

      <Panel
        title="Headline metrics"
        description="Retrieval quality, judge validation, and evaluation volume — the three signals that summarise platform health."
      >
        {metrics.status === 'loading' || metrics.status === 'idle' ? (
          <LoadingRows cols={3} />
        ) : metrics.status === 'error' ? (
          <ErrorState
            error={metrics.error}
            kind={metrics.kind}
            httpStatus={metrics.httpStatus}
            onRetry={metrics.refetch}
          />
        ) : (
          <div className="tile-grid">
            {headlineMetrics.map((metric) => (
              <StatTile
                key={metric.key}
                label={metric.label}
                metric={toTileMetric(metric)}
                unit={unit(metric)}
                format={formatMetric(metric)}
              />
            ))}
          </div>
        )}
      </Panel>

      <Panel
        title="Supporting metrics"
        description="These complete the operational picture without crowding the dashboard with charts."
      >
        {metrics.status === 'loading' || metrics.status === 'idle' ? (
          <LoadingRows cols={4} />
        ) : metrics.status === 'error' ? (
          <ErrorState
            error={metrics.error}
            kind={metrics.kind}
            httpStatus={metrics.httpStatus}
            onRetry={metrics.refetch}
          />
        ) : (
          <div className="tile-grid">
            {supportingMetrics.map((metric) => (
              <StatTile
                key={metric.key}
                label={metric.label}
                metric={toTileMetric(metric)}
                unit={unit(metric)}
                format={formatMetric(metric)}
              />
            ))}
          </div>
        )}
      </Panel>

      {metrics.status === 'success' ? (
        <Panel
          title="Metric provenance"
          description="This table is deliberately plain: it shows where each value came from and why some values cannot be claimed yet."
          flush
        >
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Metric</th>
                  <th>Status</th>
                  <th>Source</th>
                  <th>Note</th>
                </tr>
              </thead>
              <tbody>
                {ordered.map((metric) => (
                  <tr key={metric.key}>
                    <td>{metric.label}</td>
                    <td>{metric.status.replace('_', ' ')}</td>
                    <td className={metric.source ? 'mono muted' : 'absent'}>
                      {metric.source ?? 'No artifact yet'}
                    </td>
                    <td>{sourceText(metric)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      ) : null}

      <Callout tone="warn" glyph="!">
        Mock agreement is useful harness evidence, not judge-validation evidence.
        A dashboard should make that distinction visible because real measured
        values are more credible than impressive numbers without receipts.
      </Callout>
    </>
  )
}
