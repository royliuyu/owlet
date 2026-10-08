import { useState } from 'react'
import { Trash2 } from 'lucide-react'
import { ApiError, removeCollection, updateCollection } from '@/lib/api'
import type { Collection } from '@/lib/types'

export function FolderList({
  collections,
  onChanged,
  onRemoved,
  onRemoveFailed,
}: {
  collections: Collection[]
  onChanged: () => void
  onRemoved: (collection: Collection) => void
  onRemoveFailed: (collection: Collection, message: string) => void
}) {
  const [error, setError] = useState<string | null>(null)
  const [removingId, setRemovingId] = useState<string | null>(null)

  function run(work: Promise<unknown>, fallback: string) {
    setError(null)
    work.then(onChanged).catch((reason: unknown) => {
      setError(reason instanceof ApiError ? reason.message : fallback)
    })
  }

  function remove(collection: Collection) {
    if (removingId) return
    setError(null)
    setRemovingId(collection.id)
    removeCollection(collection.id)
      .then(() => onRemoved(collection))
      .catch((reason: unknown) => {
        const message = reason instanceof ApiError ? reason.message : 'Could not remove the folder'
        onRemoveFailed(collection, message)
      })
      .finally(() => setRemovingId((current) => (current === collection.id ? null : current)))
  }

  return (
    <div>
      {error ? <p className="mb-2 text-sm text-danger">{error}</p> : null}
      <ul className="flex flex-col gap-2">
        {collections.map((collection) => {
          const removing = removingId === collection.id
          return (
            <li
              key={collection.id}
              aria-busy={removing}
              className="flex items-start gap-3 rounded-xl border border-line bg-paper px-3 py-3"
            >
              <input
                type="checkbox"
                checked={collection.enabled}
                aria-label={`Read ${collection.label}`}
                onChange={(event) =>
                  run(
                    updateCollection(collection.id, { enabled: event.target.checked }),
                    'Could not update the folder',
                  )
                }
                className="mt-1 size-4 accent-ink"
              />
              <div className="min-w-0 flex-1">
                <p className={collection.enabled ? 'font-medium' : 'font-medium text-muted'}>
                  {collection.label}
                </p>
                <p className="mt-1 break-all font-mono text-xs text-muted">{collection.path}</p>
              </div>
              <button
                type="button"
                aria-label={`Remove ${collection.label}`}
                disabled={removingId !== null}
                onClick={() => remove(collection)}
                className="flex items-center gap-1 rounded p-1 text-muted hover:text-danger disabled:opacity-40"
              >
                {removing ? <span className="text-xs">Removing…</span> : null}
                <Trash2 size={16} />
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
