import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useCallback } from 'react'
import { api } from '../api/client'
import { useApi } from '../hooks/useApi'
import { ThemeToggle } from './ThemeToggle'

export interface RouteMeta {
  path: string
  label: string
  title: string
  description: string
  /** Grouping label in the sidebar. */
  group: 'Evaluation' | 'Operations'
  /** Shown as a small trailing hint when the page's data is not live. */
  hint?: string
}

export const ROUTES: RouteMeta[] = [
  {
    path: '/',
    label: 'Overview',
    title: 'Overview',
    description:
      'Platform state and what each headline number is actually backed by.',
    group: 'Evaluation',
  },
  {
    path: '/retrieval',
    label: 'Retrieval',
    title: 'Retrieval benchmark',
    description:
      'Dense vs BM25 vs hybrid RRF on the held-out 120-query labelled set.',
    group: 'Evaluation',
  },
  {
    path: '/judges',
    label: 'Judges',
    title: 'Judge validation',
    description:
      'Dual-judge agreement on the 120-answer validation slice, and bulk judging capacity.',
    group: 'Evaluation',
  },
  {
    path: '/runs',
    label: 'Runs',
    title: 'Eval runs',
    description: 'Queue an eval run and watch it move through the Redis worker.',
    group: 'Operations',
    hint: 'live',
  },
  {
    path: '/review',
    label: 'Review queue',
    title: 'Manual review queue',
    description:
      'Cases where the two judges disagreed enough to need a human decision.',
    group: 'Operations',
    hint: 'live',
  },
]

/** Small dot in the topbar: is the FastAPI backend actually up? */
function BackendStatus() {
  const fetcher = useCallback((signal: AbortSignal) => api.health(signal), [])
  const state = useApi(fetcher, [])

  const tone =
    state.status === 'success'
      ? 'pill--good'
      : state.status === 'error'
        ? 'pill--critical'
        : ''

  const text =
    state.status === 'success'
      ? 'API online'
      : state.status === 'error'
        ? 'API offline'
        : 'Checking API'

  return (
    <span
      className={`pill ${tone}`}
      title={
        state.status === 'error'
          ? state.error
          : 'GET /health via the Vite dev proxy'
      }
    >
      <span className="pill__dot" aria-hidden="true" />
      {text}
    </span>
  )
}

export function AppShell() {
  const { pathname } = useLocation()
  const active = ROUTES.find((r) => r.path === pathname) ?? ROUTES[0]
  const groups = ['Evaluation', 'Operations'] as const

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand__mark" aria-hidden="true">
            LE
          </div>
          <div>
            <div className="brand__name">LLM Eval</div>
            <div className="brand__sub">Regression platform</div>
          </div>
        </div>

        {groups.map((group) => (
          <nav className="nav" key={group} aria-label={group}>
            <div className="nav__label">{group}</div>
            {ROUTES.filter((r) => r.group === group).map((route) => (
              <NavLink
                key={route.path}
                to={route.path}
                end={route.path === '/'}
                className={({ isActive }) =>
                  `nav__item${isActive ? ' nav__item--active' : ''}`
                }
              >
                <span>{route.label}</span>
                {route.hint ? (
                  <span className="badge badge--neutral">{route.hint}</span>
                ) : null}
              </NavLink>
            ))}
          </nav>
        ))}

        <div className="sidebar__footer">
          <div>
            Numbers are tagged <strong>measured</strong>, <strong>non-final</strong>,{' '}
            <strong>placeholder</strong> or <strong>not measured</strong>.
          </div>
          <div className="muted">Dashboard values come from API data.</div>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <div className="topbar__titles">
            <h1>{active.title}</h1>
            <p>{active.description}</p>
          </div>
          <div className="topbar__actions">
            <BackendStatus />
            <ThemeToggle />
          </div>
        </header>
        <main className="page">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
