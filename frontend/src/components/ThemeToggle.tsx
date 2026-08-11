import { useEffect, useState } from 'react'

/**
 * Light / dark / follow-OS.
 *
 * Dark mode here is not an automatic inversion — tokens.css declares a
 * separately chosen set of steps for the dark surface, validated against it.
 * This component only decides *which* set applies, by stamping data-theme on
 * <html>; when the choice is "system" the attribute is removed and the
 * prefers-color-scheme media query takes over.
 */

type Choice = 'light' | 'dark' | 'system'
const KEY = 'leval-theme'

function read(): Choice {
  try {
    const stored = localStorage.getItem(KEY)
    if (stored === 'light' || stored === 'dark') return stored
  } catch {
    // localStorage can throw in private modes — fall through to system.
  }
  return 'system'
}

export function ThemeToggle() {
  const [choice, setChoice] = useState<Choice>(read)

  useEffect(() => {
    const root = document.documentElement
    if (choice === 'system') {
      root.removeAttribute('data-theme')
      try {
        localStorage.removeItem(KEY)
      } catch {
        /* ignore */
      }
    } else {
      root.setAttribute('data-theme', choice)
      try {
        localStorage.setItem(KEY, choice)
      } catch {
        /* ignore */
      }
    }
  }, [choice])

  const next: Record<Choice, Choice> = {
    system: 'light',
    light: 'dark',
    dark: 'system',
  }
  const glyph: Record<Choice, string> = { system: '◐', light: '☀', dark: '☾' }
  const label: Record<Choice, string> = {
    system: 'System theme',
    light: 'Light theme',
    dark: 'Dark theme',
  }

  return (
    <button
      className="btn btn--sm"
      onClick={() => setChoice(next[choice])}
      title={`${label[choice]} — click for ${label[next[choice]].toLowerCase()}`}
      aria-label={label[choice]}
    >
      <span aria-hidden="true">{glyph[choice]}</span>
      {choice === 'system' ? 'Auto' : choice === 'light' ? 'Light' : 'Dark'}
    </button>
  )
}
