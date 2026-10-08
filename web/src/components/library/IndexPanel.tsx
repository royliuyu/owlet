import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, cancelIndex, getIndexStatus, startIndex } from '@/lib/api'
import type { IndexStatus } from '@/lib/types'

const POLL_MS = 1500

/** Reading a folder is instant; making it searchable is not, so this reports. */
export function IndexPanel({ refreshKey = 0 }: { refreshKey?: number }) {
  const [status, setStatus] = useState<IndexStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [cancelling, setCancelling] = useState(false)
  const timer = useRef<number | null>(null)

  const refresh = useCallback(() => {
    getIndexStatus()
      .then((next) => {
        setStatus(next)
        if (!next.running) setCancelling(false)
        setError(null)
      })
      .catch((reason: unknown) => {
        setError(reason instanceof ApiError ? reason.message : 'Could not read the index')
      })
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh, refreshKey])

  useEffect(() => {
    if (!status?.running) {
      if (timer.current) window.clearTimeout(timer.current)
      return
    }
    timer.current = window.setTimeout(refresh, POLL_MS)
    return () => {
      if (timer.current) window.clearTimeout(timer.current)
    }
  }, [status, refresh])

  function stop() {
    setCancelling(true)
    setError(null)
    cancelIndex()
      .then(setStatus)
      .catch((reason: unknown) => {
        setCancelling(false)
        setError(reason instanceof ApiError ? reason.message : 'Could not cancel indexing')
      })
  }

  function build(force: boolean) {
    setError(null)
    startIndex(force)
      .then(setStatus)
      .catch((reason: unknown) => {
        setError(reason instanceof ApiError ? reason.message : 'Could not start indexing')
      })
  }

  const running = Boolean(status?.running)

  return (
    <div className="flex flex-col gap-3">
      <h2 className="font-serif text-2xl">Index folders</h2>
      <p className="text-sm text-muted">
        Chat answers come from indexed passages in the folders above. Run this after adding or
        changing files.
      </p>
      {status ? (
        <dl className="grid grid-cols-3 gap-2 text-sm">
          <Stat label="Documents" value={status.documents} />
          <Stat label="Passages" value={status.chunks} />
          <Stat label="Embedded" value={status.embedded} />
        </dl>
      ) : null}
      {running ? <Progress status={status} /> : null}
      {!running && status?.detail ? <p className="text-sm text-muted">{status.detail}</p> : null}
      {status?.failures?.length ? (
        <ul className="flex flex-col gap-1 text-sm text-danger">
          {status.failures.map((failure) => (
            <li key={failure}>{failure}</li>
          ))}
        </ul>
      ) : null}
      {error ? <p className="text-sm text-danger">{error}</p> : null}
      <div className="flex gap-2">
        <button
          type="button"
          disabled={running}
          onClick={() => build(false)}
          className="rounded-full bg-ink px-4 py-2 text-sm text-paper disabled:opacity-40"
        >
          {running
            ? status?.force
              ? 'Rebuilding…'
              : 'Indexing…'
            : 'Index new and changed files'}
        </button>
        {running ? (
          <button
            type="button"
            disabled={cancelling}
            onClick={stop}
            className="rounded-full border border-line px-4 py-2 text-sm disabled:opacity-40"
          >
            {cancelling ? 'Cancelling…' : 'Cancel'}
          </button>
        ) : (
          <button
            type="button"
            onClick={() => build(true)}
            className="rounded-full border border-line px-4 py-2 text-sm"
          >
            Rebuild everything
          </button>
        )}
      </div>
    </div>
  )
}

function Progress({ status }: { status: IndexStatus | null }) {
  if (!status) return null
  const seen = status.documents_seen ?? 0
  const updated = status.documents_indexed ?? 0
  const unchanged = status.documents_skipped ?? 0
  return (
    <p className="text-sm text-muted">
      {updated} updated, {unchanged} unchanged, of {seen}. {status.chunks_written ?? 0} passages
      written, {status.chunks_embedded ?? 0} embedded.
    </p>
  )
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl border border-line bg-paper px-3 py-2">
      <dt className="text-[11px] tracking-wide text-muted uppercase">{label}</dt>
      <dd className="mt-0.5 font-medium tabular-nums">{value.toLocaleString()}</dd>
    </div>
  )
}
