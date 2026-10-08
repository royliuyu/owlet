import { useEffect, useState } from 'react'
import { ChevronRight, CornerUpLeft, Folder } from 'lucide-react'
import { ApiError, browseFolders } from '@/lib/api'
import type { FolderListing } from '@/lib/types'

/** Walks directories on the machine running owlet, not the browser's machine. */
export function FolderBrowser({
  start,
  onUse,
  onCancel,
}: {
  start: string
  onUse: (path: string) => void
  onCancel: () => void
}) {
  const [location, setLocation] = useState(start)
  const [listing, setListing] = useState<FolderListing | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    browseFolders(location)
      .then((next) => {
        if (cancelled) return
        setListing(next)
        setError(null)
      })
      .catch((reason: unknown) => {
        if (cancelled) return
        setListing(null)
        setError(reason instanceof ApiError ? reason.message : 'Could not open that folder')
      })
    return () => {
      cancelled = true
    }
  }, [location])

  const here = listing?.path ?? ''

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center gap-2 border-b border-line px-3 py-2">
        {listing?.parent != null ? (
          <button
            type="button"
            aria-label="Up one folder"
            onClick={() => setLocation(listing.parent ?? '')}
            className="rounded p-1 text-muted hover:text-ink"
          >
            <CornerUpLeft size={16} />
          </button>
        ) : null}
        <p className="min-w-0 flex-1 truncate font-mono text-xs">{here || 'This computer'}</p>
      </div>
      {error ? (
        <div className="px-3 py-3">
          <p className="text-sm text-danger">{error}</p>
          {location ? (
            <button
              type="button"
              onClick={() => setLocation('')}
              className="mt-2 text-sm text-muted underline"
            >
              This computer
            </button>
          ) : null}
        </div>
      ) : null}
      {!listing && !error ? <p className="px-3 py-3 text-sm text-muted">Opening…</p> : null}
      {listing && listing.entries.length === 0 ? (
        <p className="px-3 py-3 text-sm text-muted">No folders inside.</p>
      ) : null}
      {listing && listing.entries.length > 0 ? (
        <ul className="min-h-0 flex-1 overflow-auto">
          {listing.entries.map((entry) => (
            <li key={entry.path}>
              <button
                type="button"
                onClick={() => setLocation(entry.path)}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-paper-raised"
              >
                <Folder size={16} className="shrink-0 text-muted" />
                <span className="min-w-0 flex-1 truncate">{entry.name}</span>
                <ChevronRight size={14} className="shrink-0 text-muted" />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <div className="flex shrink-0 justify-end gap-2 border-t border-line px-3 py-2">
        <button type="button" onClick={onCancel} className="rounded-full px-3 py-1.5 text-sm">
          Cancel
        </button>
        <button
          type="button"
          disabled={!here}
          onClick={() => onUse(here)}
          className="rounded-full bg-ink px-3 py-1.5 text-sm text-paper disabled:opacity-40"
        >
          Select folder
        </button>
      </div>
    </div>
  )
}
