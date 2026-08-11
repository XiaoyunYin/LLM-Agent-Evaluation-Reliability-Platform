import type { Metric } from '../types/provenance'
import { ProvenanceBadge, provenanceTitle } from './ProvenanceBadge'

/**
 * A single headline number. Per the form heuristic: one current value is a
 * stat tile, not a one-bar bar chart.
 *
 * The interesting branch is `not_measured`. It renders an em-dash on a hatched
 * surface with a dashed border — visually a *hole*, not a low value. Rendering
 * "0" there would be a lie that looks like data, and 0 is exactly what a naive
 * `metric.value ?? 0` would produce. The type system prevents that: in this
 * branch `metric` has no `value` to read.
 */

export interface StatTileProps {
  label: string
  metric: Metric<number>
  /** Suffix rendered smaller and dimmer: '%', 'tok/s', 'docs'. */
  unit?: string
  /** How to print the number. Defaults to locale integer formatting. */
  format?: (value: number) => string
  /** Optional target for context, e.g. 8000. Shown only as text. */
  target?: number
  targetLabel?: string
}

const defaultFormat = (value: number) => value.toLocaleString()

export function StatTile({
  label,
  metric,
  unit,
  format = defaultFormat,
  target,
  targetLabel,
}: StatTileProps) {
  const title = provenanceTitle(metric)
  const isAbsent = metric.status === 'not_measured'

  return (
    <div className={`tile${isAbsent ? ' tile--unmeasured' : ''}`}>
      <div className="tile__label">
        <span>{label}</span>
        <ProvenanceBadge status={metric.status} title={title} />
      </div>

      {isAbsent ? (
        <div className="tile__value tile__value--absent" title={title}>
          <span aria-hidden="true">—</span>
          <span className="sr-only">Not measured</span>
        </div>
      ) : (
        <div className="tile__value" title={title}>
          {format(metric.value)}
          {unit ? <span className="tile__unit">{unit}</span> : null}
        </div>
      )}

      <div className="tile__foot">
        {isAbsent
          ? metric.blockedBy
            ? `Blocked: ${metric.blockedBy}`
            : metric.note
          : metric.status === 'placeholder' || metric.status === 'non_final'
            ? metric.note
            : metric.source}
        {target !== undefined ? (
          <>
            {' '}
            <span className="muted">
              · {targetLabel ?? 'Target'} {format(target)}
              {unit ?? ''}
            </span>
          </>
        ) : null}
      </div>
    </div>
  )
}

/**
 * Formats a 0–1 fraction as a percentage figure.
 *
 * Agreement, routing rate and every other rate are stored in the snapshot as
 * fractions (0.84), matching how the Python side computes them. A tile with
 * `unit="%"` and no formatter would render that as "0.84%" — off by 100×, and
 * plausible enough to survive review. Pass this formatter with `unit="%"`, and
 * pass the target as a fraction too so both go through it.
 */
export const asPercent = (value: number) => (value * 100).toFixed(1)
