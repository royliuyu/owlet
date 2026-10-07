import { useState, type FormEvent } from 'react'
import { ApiError, addCollection } from '@/lib/api'
import type { Collection } from '@/lib/types'

/**
 * The path is read on the machine running owlet, which may not be the
 * machine running the browser, so this is a typed path and not a file
 * picker. The server checks that the folder exists before saving it.
 */
export function AddFolderForm({ onAdded }: { onAdded: (collection: Collection) => void }) {
  const [path, setPath] = useState('')
  const [label, setLabel] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  function submit(event: FormEvent) {
    event.preventDefault()
    if (saving || !path.trim()) return
    setSaving(true)
    setError(null)
    addCollection({ path: path.trim(), label: label.trim() || undefined })
      .then((collection) => {
        setPath('')
        setLabel('')
        onAdded(collection)
      })
      .catch((reason: unknown) => {
        setError(reason instanceof ApiError ? reason.message : 'Could not add the folder')
      })
      .finally(() => setSaving(false))
  }

  return (
    <form className="flex flex-col gap-3" onSubmit={submit}>
      <div className="flex flex-col gap-1">
        <label htmlFor="folder-path" className="text-sm font-medium">
          Folder on this computer
        </label>
        <input
          id="folder-path"
          value={path}
          spellCheck={false}
          placeholder="D:/papers"
          onChange={(event) => setPath(event.target.value)}
          className="rounded-xl border border-line bg-paper px-3 py-3 font-mono text-sm outline-none focus:border-accent"
        />
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="folder-label" className="text-sm font-medium">
          Name <span className="font-normal text-muted">(optional)</span>
        </label>
        <input
          id="folder-label"
          value={label}
          placeholder="Papers"
          onChange={(event) => setLabel(event.target.value)}
          className="rounded-xl border border-line bg-paper px-3 py-3 text-base outline-none focus:border-accent"
        />
      </div>
      <button
        type="submit"
        disabled={saving || !path.trim()}
        className="self-start rounded-full bg-ink px-4 py-2 text-sm text-paper disabled:opacity-40"
      >
        {saving ? 'Checking…' : 'Add folder'}
      </button>
      {error ? <p className="text-sm text-danger">{error}</p> : null}
      <p className="text-sm text-muted">
        PDF, Word (.docx), Markdown, and plain text files under the folder are picked up.
        Nothing is copied.
      </p>
    </form>
  )
}
