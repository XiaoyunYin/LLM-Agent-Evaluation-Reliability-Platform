import type { Metric, MetricStatus } from '../types/provenance'
import { STATUS_LABEL } from '../types/provenance'

const GLYPH: Record<MetricStatus, string> = {
  measured: 'M',
  non_final: 'N',
  placeholder: 'P',
  not_measured: 'O',
}

const CLASS: Record<MetricStatus, string> = {
  measured: 'badge--measured',
  non_final: 'badge--non-final',
  placeholder: 'badge--placeholder',
  not_measured: 'badge--not-measured',
}

export function ProvenanceBadge({
  status,
  title,
}: {
  status: MetricStatus
  title?: string
}) {
  return (
    <span className={`badge ${CLASS[status]}`} title={title}>
      <span className="badge__glyph" aria-hidden="true">
        {GLYPH[status]}
      </span>
      {STATUS_LABEL[status]}
    </span>
  )
}

export function provenanceTitle(metric: Metric<unknown>): string {
  switch (metric.status) {
    case 'measured':
      return [
        `Measured ${metric.measuredAt}`,
        `Source: ${metric.source}`,
        metric.command ? `Command: ${metric.command}` : null,
      ]
        .filter(Boolean)
        .join('\n')
    case 'non_final':
      return [
        `Non-final${metric.measuredAt ? ` ${metric.measuredAt}` : ''}`,
        `Source: ${metric.source}`,
        metric.note,
        metric.command ? `Command: ${metric.command}` : null,
      ]
        .filter(Boolean)
        .join('\n')
    case 'placeholder':
      return [`Placeholder - ${metric.note}`, `Source: ${metric.source}`].join('\n')
    case 'not_measured':
      return [
        metric.note,
        metric.blockedBy ? `Blocked by: ${metric.blockedBy}` : null,
        metric.command ? `Unblock with: ${metric.command}` : null,
      ]
        .filter(Boolean)
        .join('\n')
  }
}
