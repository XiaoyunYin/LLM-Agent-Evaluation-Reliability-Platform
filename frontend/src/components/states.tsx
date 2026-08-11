/**
 * The three async states a table can be in, drawn explicitly.
 *
 * Splitting "loading", "empty" and "error" into distinct components forces
 * every call site to decide what each one says. The alternative — one spinner
 * and an empty <tbody> — is how dashboards end up implying "no runs exist"
 * when the truth is "the backend is not running".
 */

export function LoadingRows({ rows = 3, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <div className="stack" style={{ padding: 18, gap: 10 }} aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading…</span>
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} style={{ display: 'flex', gap: 10 }}>
          {Array.from({ length: cols }).map((_, c) => (
            <div
              key={c}
              className="skeleton"
              style={{ height: 14, flex: c === 0 ? 2 : 1 }}
            />
          ))}
        </div>
      ))}
    </div>
  )
}

export function EmptyState({
  title,
  body,
  action,
}: {
  title: string
  body: string
  action?: React.ReactNode
}) {
  return (
    <div className="state">
      <div className="state__title">{title}</div>
      <p className="state__body">{body}</p>
      {action}
    </div>
  )
}

export function ErrorState({
  error,
  kind,
  httpStatus,
  onRetry,
}: {
  error: string
  kind: 'network' | 'http'
  httpStatus?: number
  onRetry?: () => void
}) {
  const isBackendDown = kind === 'network'

  return (
    <div className="state state--error" role="alert">
      <div className="state__title">
        {isBackendDown
          ? 'Backend unreachable'
          : `Request failed${httpStatus ? ` (${httpStatus})` : ''}`}
      </div>
      <p className="state__body">
        {error}
        {isBackendDown ? (
          <>
            {' '}
            Start it with{' '}
            <code>
              .\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload
            </code>{' '}
            from the project root, then retry.
          </>
        ) : null}
      </p>
      {onRetry ? (
        <button className="btn btn--sm" onClick={onRetry}>
          Retry
        </button>
      ) : null}
    </div>
  )
}
