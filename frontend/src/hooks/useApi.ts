/**
 * useApi — one hook, four states, no ambiguity.
 *
 * The bug this exists to prevent: `const [data, setData] = useState([])`.
 * With that, "still loading" and "loaded, and there is genuinely nothing"
 * are the same value, so the UI shows an empty table before it has asked
 * the question. A dashboard about measurement integrity must not do that.
 *
 * So the state is a discriminated union — `idle | loading | success | error` —
 * and callers must handle each branch. Same idea as the Metric type: make the
 * impossible state unrepresentable rather than remembering not to write it.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, NetworkError } from '../api/client'

export type AsyncState<T> =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'success'; data: T; fetchedAt: Date }
  | { status: 'error'; error: string; kind: 'network' | 'http'; httpStatus?: number }

export function describeError(error: unknown): {
  error: string
  kind: 'network' | 'http'
  httpStatus?: number
} {
  if (error instanceof ApiError) {
    return { error: error.message, kind: 'http', httpStatus: error.status }
  }
  if (error instanceof NetworkError) {
    return { error: error.message, kind: 'network' }
  }
  return {
    error: error instanceof Error ? error.message : String(error),
    kind: 'network',
  }
}

/**
 * @param fetcher  Must be stable (wrap in useCallback) or the effect re-runs
 *                 forever — the classic useEffect infinite loop.
 * @param deps     Re-fetch when these change.
 */
export function useApi<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  deps: React.DependencyList = [],
): AsyncState<T> & { refetch: () => void } {
  const [state, setState] = useState<AsyncState<T>>({ status: 'idle' })
  const [nonce, setNonce] = useState(0)

  // Held in a ref so `refetch` never changes identity and can be passed to
  // memoised children without invalidating them.
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  const refetch = useCallback(() => setNonce((n) => n + 1), [])

  useEffect(() => {
    const controller = new AbortController()
    setState({ status: 'loading' })

    fetcherRef.current(controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return
        setState({ status: 'success', data, fetchedAt: new Date() })
      })
      .catch((error: unknown) => {
        // An abort means "we no longer care", not "it failed". Painting an
        // error here produces the flash of red you see in a lot of dashboards
        // during fast navigation.
        if (controller.signal.aborted) return
        if (error instanceof DOMException && error.name === 'AbortError') return
        setState({ status: 'error', ...describeError(error) })
      })

    return () => controller.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce])

  return { ...state, refetch }
}
