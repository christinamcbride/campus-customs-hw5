import { useEffect, useRef } from 'react'

/**
 * Run an async job on an interval, and again whenever `deps` change.
 *
 * Overlapping calls are skipped rather than queued: the agent run is the slow
 * thing here, and a backed-up queue of stale event requests would make the
 * feed jump around. Pass `ms = null` to stop polling entirely.
 */
export function usePoll(job: () => Promise<void> | void, ms: number | null, deps: unknown[] = []) {
  const saved = useRef(job)
  saved.current = job

  useEffect(() => {
    let alive = true
    let busy = false

    const tick = async () => {
      if (busy || !alive) return
      busy = true
      try {
        await saved.current()
      } finally {
        busy = false
      }
    }

    void tick()
    if (ms === null) return () => { alive = false }

    const id = window.setInterval(tick, ms)
    return () => {
      alive = false
      window.clearInterval(id)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ms, ...deps])
}
