import { useState } from 'react'
import { Trash2 } from 'lucide-react'
import { ApiError, removeCollection, updateCollection } from '@/lib/api'
import type { Collection } from '@/lib/types'

export function FolderList({
  collections,
  onChanged,
}: {
  collections: Collection[]
  onChanged: () => void
}) {
  const [error, setError] = useState<string | null>(null)

  function run(work: Promise<unknown>, fallback: string) {
    setError(null)
    work.then(onChanged).catch((reason: unknown) => {
      setError(reason instanceof ApiError ? reason.message : fallback)
    })
  }

  return (
    <div>
      {error ? <p className="mb-2 text-sm text-danger">{error}</p> : null}
      <ul className="flex flex-col gap-2">
        {collections.map((collection) => (
          <li
            key={collection.id}
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
              onClick={() =>
                run(removeCollection(collection.id), 'Could not remove the folder')
              }
              className="rounded p-1 text-muted hover:text-danger"
            >
              <Trash2 size={16} />
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
