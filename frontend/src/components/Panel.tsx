import type { ReactNode } from 'react'

export function Panel({
  title,
  description,
  actions,
  children,
  flush = false,
}: {
  title: string
  description?: ReactNode
  actions?: ReactNode
  children: ReactNode
  /** Removes body padding — use when the child is a full-bleed table. */
  flush?: boolean
}) {
  return (
    <section className="panel">
      <header className="panel__head">
        <div>
          <h2 className="panel__title">{title}</h2>
          {description ? <p className="panel__desc">{description}</p> : null}
        </div>
        {actions ? <div className="topbar__actions">{actions}</div> : null}
      </header>
      <div className={`panel__body${flush ? ' panel__body--flush' : ''}`}>
        {children}
      </div>
    </section>
  )
}

export function Callout({
  tone = 'neutral',
  glyph = 'ℹ',
  children,
}: {
  tone?: 'neutral' | 'warn'
  glyph?: string
  children: ReactNode
}) {
  return (
    <div className={`callout${tone === 'warn' ? ' callout--warn' : ''}`}>
      <span className="callout__glyph" aria-hidden="true">
        {glyph}
      </span>
      <div>{children}</div>
    </div>
  )
}
