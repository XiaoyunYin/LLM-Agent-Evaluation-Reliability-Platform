import { useId, useState } from 'react'
import type { Metric } from '../../types/provenance'
import { provenanceTitle } from '../ProvenanceBadge'

/**
 * Horizontal bar comparison, built from plain HTML rather than SVG.
 *
 * Why HTML: labels stay real DOM text at a real font size, so nothing scales
 * with the container the way SVG <text> does. Percentage widths make it
 * responsive for free, with no ResizeObserver.
 *
 * Three decisions worth defending in an interview:
 *
 * 1. THE DOMAIN IS FIXED AT 0–1, not scaled to the data. recall@10 and nDCG@10
 *    are bounded scores. Auto-scaling to max would stretch BM25's 0.0667 to
 *    full width and make a poor retrieval result look like a triumph. The bar
 *    should look small, because it is small.
 *
 * 2. AN UNMEASURED SERIES IS NOT A ZERO-LENGTH BAR. It gets a hatched, dashed
 *    track with the words "not measured" — visually a hole in the chart. A
 *    zero-length bar would read as "we measured it and it scored nothing".
 *
 * 3. VALUES ARE DIRECT-LABELLED IN TEXT INK, never in the series colour. The
 *    palette check flagged that light-mode aqua sits below 3:1 against the
 *    surface; direct labels plus the table view are the required relief.
 */

export interface BarRow {
  key: string
  label: string
  /** CSS custom property name, e.g. '--series-1'. */
  colorVar: string
  metric: Metric<number>
  sublabel?: string
}

export interface BarComparisonProps {
  rows: BarRow[]
  /** Upper bound of the scale. Bounded scores should keep the default. */
  domainMax?: number
  format?: (value: number) => string
  /** Named in the caption so a single-series chart needs no legend box. */
  caption: string
}

const TICKS = [0, 0.25, 0.5, 0.75, 1]

export function BarComparison({
  rows,
  domainMax = 1,
  format = (v) => v.toFixed(4),
  caption,
}: BarComparisonProps) {
  const [showTable, setShowTable] = useState(false)
  const [hovered, setHovered] = useState<string | null>(null)
  const tableId = useId()

  const measuredRows = rows.filter((r) => r.metric.status !== 'not_measured')

  return (
    <figure className="bars" aria-describedby={tableId}>
      <figcaption className="bars__caption">
        <span>{caption}</span>
        <button
          className="btn btn--sm"
          onClick={() => setShowTable((s) => !s)}
          aria-expanded={showTable}
        >
          {showTable ? 'Show chart' : 'Show table'}
        </button>
      </figcaption>

      {showTable ? (
        <BarTable id={tableId} rows={rows} format={format} />
      ) : (
        <>
          {/* Legend is always present for >= 2 series, so identity is never
              carried by colour alone. */}
          <div className="chart__legend">
            {rows.map((row) => (
              <span className="chart__legend-item" key={row.key}>
                <span
                  className={
                    row.metric.status === 'not_measured'
                      ? 'chart__swatch chart__swatch--ghost'
                      : 'chart__swatch'
                  }
                  style={
                    row.metric.status === 'not_measured'
                      ? undefined
                      : { background: `var(${row.colorVar})` }
                  }
                  aria-hidden="true"
                />
                {row.label}
              </span>
            ))}
          </div>

          <div className="bars__plot">
            {/* Recessive gridlines, drawn behind the marks. */}
            <div className="bars__grid" aria-hidden="true">
              {TICKS.map((t) => (
                <span key={t} className="bars__gridline" style={{ left: `${t * 100}%` }} />
              ))}
            </div>

            {rows.map((row) => {
              // Aliased to a local const so TypeScript narrows the union: the
              // compiler will not carry a narrowing from `row.metric.status`
              // through to a later `row.metric.value` read.
              const metric = row.metric
              const absent = metric.status === 'not_measured'
              const pct = metric.status === 'not_measured'
                ? 0
                : Math.max(0, Math.min(100, (metric.value / domainMax) * 100))
              const title = provenanceTitle(metric)

              return (
                <div
                  className="bars__row"
                  key={row.key}
                  onMouseEnter={() => setHovered(row.key)}
                  onMouseLeave={() => setHovered(null)}
                  onFocus={() => setHovered(row.key)}
                  onBlur={() => setHovered(null)}
                  tabIndex={0}
                  title={title}
                  aria-label={`${row.label}: ${
                    metric.status === 'not_measured'
                      ? 'not measured'
                      : format(metric.value)
                  }`}
                >
                  <div className="bars__name">
                    {row.label}
                    {row.sublabel ? (
                      <span className="bars__sublabel">{row.sublabel}</span>
                    ) : null}
                  </div>

                  <div className={`bars__track${absent ? ' bars__track--ghost' : ''}`}>
                    {absent ? (
                      <span className="bars__ghost-text">not measured</span>
                    ) : (
                      <div
                        className={`bars__fill${
                          hovered === row.key ? ' bars__fill--hot' : ''
                        }`}
                        style={{
                          width: `${pct}%`,
                          background: `var(${row.colorVar})`,
                        }}
                      />
                    )}
                  </div>

                  {/* Direct label — text ink, not the series colour. */}
                  <div className={`bars__value${absent ? ' absent' : ''}`}>
                    {metric.status === 'not_measured' ? '—' : format(metric.value)}
                  </div>
                </div>
              )
            })}

            <div className="bars__axis" aria-hidden="true">
              {TICKS.map((t) => (
                <span key={t} className="bars__tick" style={{ left: `${t * 100}%` }}>
                  {(t * domainMax).toFixed(2)}
                </span>
              ))}
            </div>
          </div>

          {measuredRows.length < rows.length ? (
            <p className="bars__footnote">
              {rows.length - measuredRows.length} of {rows.length} strategies have
              no measurement. The scale is fixed at 0–{domainMax} so the measured
              bar is not visually inflated.
            </p>
          ) : null}
        </>
      )}
    </figure>
  )
}

/** The table view — the accessibility relief and the honest fallback. */
function BarTable({
  id,
  rows,
  format,
}: {
  id: string
  rows: BarRow[]
  format: (value: number) => string
}) {
  return (
    <div className="table-wrap">
      <table className="data" id={id}>
        <thead>
          <tr>
            <th>Strategy</th>
            <th className="num">Value</th>
            <th>Provenance</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key}>
              <td>{row.label}</td>
              <td className="num">
                {row.metric.status === 'not_measured' ? (
                  <span className="absent">—</span>
                ) : (
                  format(row.metric.value)
                )}
              </td>
              <td>
                {row.metric.status === 'not_measured'
                  ? (row.metric.blockedBy ?? row.metric.note)
                  : row.metric.status === 'measured'
                    ? row.metric.source
                    : row.metric.note}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
