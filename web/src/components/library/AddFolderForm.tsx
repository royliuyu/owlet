import { useEffect, useLayoutEffect, useRef, useState, type FormEvent } from 'react'
import { createPortal } from 'react-dom'
import { ApiError, addCollection } from '@/lib/api'
import type { Collection } from '@/lib/types'
import { FolderBrowser } from '@/components/library/FolderBrowser'

/**
 * The path is read on the machine running owlet. Browse asks that machine
 * which folders it can see, because a browser file dialog would name a
 * folder on the machine running the browser instead.
 */
export function AddFolderForm({ onAdded }: { onAdded: (collection: Collection) => void }) {
  const [path, setPath] = useState('')
  const [label, setLabel] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [browsing, setBrowsing] = useState(false)
  const [browseStart, setBrowseStart] = useState('')
  const browseButton = useRef<HTMLButtonElement>(null)
  const popover = useRef<HTMLDivElement>(null)

  useLayoutEffect(() => {
    if (!browsing) return
    const button = browseButton.current
    const panel = popover.current
    if (!button || !panel) return

    function place() {
      const anchor = browseButton.current
      const dialog = popover.current
      if (!anchor || !dialog) return
      const rect = anchor.getBoundingClientRect()
      const width = dialog.offsetWidth
      const gap = 6
      let left = rect.right - width
      left = Math.max(8, Math.min(left, window.innerWidth - width - 8))
      dialog.style.top = `${rect.bottom + gap}px`
      dialog.style.left = `${left}px`
      dialog.style.maxHeight = `${Math.max(160, window.innerHeight - rect.bottom - gap - 8)}px`
    }

    place()
    const observer = new ResizeObserver(place)
    observer.observe(panel)
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => {
      observer.disconnect()
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
    }
  }, [browsing])

  useEffect(() => {
    if (!browsing) return
    function onPointer(event: MouseEvent) {
      const target = event.target
      if (!(target instanceof Node)) return
      if (popover.current?.contains(target) || browseButton.current?.contains(target)) return
      setBrowsing(false)
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') setBrowsing(false)
    }
    document.addEventListener('mousedown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [browsing])

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
        <div className="flex gap-2">
          <input
            id="folder-path"
            value={path}
            spellCheck={false}
            placeholder="D:/papers"
            onChange={(event) => setPath(event.target.value)}
            className="min-w-0 flex-1 rounded-xl border border-line bg-paper px-3 py-3 font-mono text-sm outline-none focus:border-accent"
          />
          <button
            ref={browseButton}
            type="button"
            aria-expanded={browsing}
            aria-haspopup="dialog"
            onClick={() => {
              setBrowseStart(path.trim())
              setBrowsing((open) => !open)
            }}
            className="rounded-full border border-line px-4 py-2 text-sm"
          >
            Browse
          </button>
        </div>
        {browsing
          ? createPortal(
              <div
                ref={popover}
                role="dialog"
                aria-label="Choose a folder"
                className="fixed z-50 flex w-80 flex-col overflow-hidden rounded-xl border border-line bg-paper shadow-xl"
              >
                <FolderBrowser
                  key={browseStart}
                  start={browseStart}
                  onUse={(chosen) => {
                    setPath(chosen)
                    setBrowsing(false)
                  }}
                  onCancel={() => setBrowsing(false)}
                />
              </div>,
              document.body,
            )
          : null}
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
