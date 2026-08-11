/**
 * Run / review status, rendered as a pill.
 *
 * Status colours come from the reserved status palette (good / warning /
 * serious / critical) and are never reused as series colours — a chart series
 * must never be able to impersonate "failed". Each pill also carries its word,
 * so hue is never the only channel.
 */

const RUN_TONE: Record<string, string> = {
  completed: 'pill--good',
  running: 'pill--running',
  queued: 'pill--warning',
  pending: 'pill--warning',
  failed: 'pill--critical',
}

const REVIEW_TONE: Record<string, string> = {
  pending: 'pill--warning',
  reviewed: 'pill--running',
  resolved: 'pill--good',
}

export function StatusPill({
  value,
  kind = 'run',
}: {
  value: string
  kind?: 'run' | 'review'
}) {
  const map = kind === 'review' ? REVIEW_TONE : RUN_TONE
  const tone = map[value.toLowerCase()] ?? ''
  return (
    <span className={`pill ${tone}`}>
      <span className="pill__dot" aria-hidden="true" />
      {value}
    </span>
  )
}
