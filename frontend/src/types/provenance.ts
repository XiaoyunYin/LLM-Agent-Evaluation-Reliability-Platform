/**
 * The provenance model.
 *
 * This is the single most important type in the dashboard. An evaluation
 * platform whose UI cannot tell "0.0667, measured by running the benchmark"
 * apart from "0, because nobody has run anything yet" is worse than no
 * dashboard, because it launders guesses into screenshots.
 *
 * So a metric is a discriminated union, and `NotMeasured` has **no `value`
 * property at all**. That is the whole trick: TypeScript makes it a compile
 * error to render a number for something that was never measured. You cannot
 * forget, because the code will not build.
 *
 *   const m: Metric = { status: 'not_measured', note: '...' }
 *   m.value          // ✗ Property 'value' does not exist on type ...
 *   if (m.status === 'measured') m.value   // ✓ narrowed, safe
 */

export type MetricStatus = 'measured' | 'non_final' | 'placeholder' | 'not_measured'

/** A number produced by actually running code. Carries its receipt. */
export interface MeasuredMetric<T> {
  status: 'measured'
  value: T
  /** Where it came from: a script, a build-log session, a benchmark file. */
  source: string
  /** ISO date (or session marker) of the measurement. */
  measuredAt: string
  /** The exact command that reproduces it, if there is one. */
  command?: string
}

/** A real artifact value that is explicitly not a final quality metric. */
export interface NonFinalMetric<T> {
  status: 'non_final'
  value: T
  source: string
  measuredAt?: string
  command?: string
  note: string
}

/**
 * A hardcoded stand-in that the system currently serves. It has a value, but
 * that value means nothing. Rendered with a warning treatment so it can never
 * be mistaken for a result.
 */
export interface PlaceholderMetric<T> {
  status: 'placeholder'
  value: T
  source: string
  note: string
}

/** No measurement exists. Deliberately valueless. */
export interface NotMeasuredMetric {
  status: 'not_measured'
  /** What would have to happen for this to become a number. */
  note: string
  /** The concrete thing standing in the way. */
  blockedBy?: string
  /** The command to run once unblocked. */
  command?: string
}

export type Metric<T = number> =
  | MeasuredMetric<T>
  | NonFinalMetric<T>
  | PlaceholderMetric<T>
  | NotMeasuredMetric

/* ------------------------------------------------------------------ */
/* Constructors — short enough that the snapshot file stays readable.  */
/* ------------------------------------------------------------------ */

export function measured<T>(
  value: T,
  source: string,
  measuredAt: string,
  command?: string,
): MeasuredMetric<T> {
  return { status: 'measured', value, source, measuredAt, command }
}

export function placeholder<T>(
  value: T,
  source: string,
  note: string,
): PlaceholderMetric<T> {
  return { status: 'placeholder', value, source, note }
}

export function nonFinal<T>(
  value: T,
  source: string,
  note: string,
  measuredAt?: string,
  command?: string,
): NonFinalMetric<T> {
  return { status: 'non_final', value, source, note, measuredAt, command }
}

export function notMeasured(
  note: string,
  blockedBy?: string,
  command?: string,
): NotMeasuredMetric {
  return { status: 'not_measured', note, blockedBy, command }
}

/* ------------------------------------------------------------------ */
/* Narrowing helpers                                                   */
/* ------------------------------------------------------------------ */

/**
 * True when the metric carries a number of any kind (real or fake).
 *
 * `T = number` is not decoration. A `NotMeasuredMetric` has no `value`, so it
 * offers no inference site for `T`; without the default, TypeScript falls back
 * to `unknown` and callers end up comparing `{}` to a number. The default is
 * what keeps `measuredValue(someNotMeasuredMetric) ?? 0` typed as a number.
 */
export function hasValue<T = number>(
  metric: Metric<T>,
): metric is MeasuredMetric<T> | NonFinalMetric<T> | PlaceholderMetric<T> {
  return metric.status !== 'not_measured'
}

/**
 * The value ONLY if it was genuinely measured.
 *
 * Use this anywhere a number feeds a decision — chart scales, pass/fail
 * checks, regression gates. Placeholder values must never reach those paths,
 * so they come back `undefined` here even though they exist.
 */
export function measuredValue<T = number>(metric: Metric<T>): T | undefined {
  return metric.status === 'measured' ? metric.value : undefined
}

export const STATUS_LABEL: Record<MetricStatus, string> = {
  measured: 'Measured',
  non_final: 'Non-final',
  placeholder: 'Placeholder',
  not_measured: 'Not measured',
}
