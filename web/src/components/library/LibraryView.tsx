import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useWorkspace } from '@/app/workspace'
import { AddFolderForm } from '@/components/library/AddFolderForm'
import { sourceRegistry } from '@/components/cards/registry'
import { ApiError, listCollections, listFiles } from '@/lib/api'
import { useBreakpoint } from '@/lib/layout'
import type { Collection, LibraryFile } from '@/lib/types'

export function LibraryView() {
  const { collectionId } = useParams()
  const breakpoint = useBreakpoint()
  const { sources, selection, openDocument } = useWorkspace()
  const [collections, setCollections] = useState<Collection[] | null>(null)
  const [filesByFolder, setFilesByFolder] = useState<Record<string, LibraryFile[]>>({})
  const [folderErrors, setFolderErrors] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)

  const reloadCollections = useCallback(() => {
    listCollections()
      .then((items) => {
        setCollections(items.filter((item) => item.enabled))
        setError(null)
      })
      .catch((reason: unknown) => {
        setError(reason instanceof ApiError ? reason.message : 'Could not load collections')
      })
  }, [])

  useEffect(reloadCollections, [reloadCollections])

  const activeId = collectionId ?? (breakpoint === 'mobile' ? undefined : collections?.[0]?.id)

  useEffect(() => {
    if (!collections) return
    let cancelled = false
    for (const collection of collections) {
      listFiles(collection.id)
        .then((items) => {
          if (!cancelled) {
            setFilesByFolder((current) => ({ ...current, [collection.id]: items }))
          }
        })
        .catch((reason: unknown) => {
          if (!cancelled) {
            const message = reason instanceof ApiError ? reason.message : 'Could not load files'
            setFolderErrors((current) => ({ ...current, [collection.id]: message }))
          }
        })
    }
    return () => {
      cancelled = true
    }
  }, [collections])

  if (error) {
    return <p className="px-6 py-8 text-sm text-danger">{error}</p>
  }
  if (!collections) {
    return <p className="px-6 py-8 text-sm text-muted">Loading the library…</p>
  }
  if (collections.length === 0) {
    return <EmptyLibrary onAdded={reloadCollections} />
  }

  const files = activeId ? filesByFolder[activeId] : undefined
  const activeError = activeId ? folderErrors[activeId] : undefined
  const visible = (files ?? []).filter((file) => sources.includes(file.source))
  const showCollections = breakpoint !== 'mobile' || !activeId
  const showFiles = breakpoint !== 'mobile' || Boolean(activeId)

  return (
    <div className="flex min-h-0 flex-1">
      {showCollections ? (
        <aside className="w-full shrink-0 overflow-auto p-3 sm:w-56 sm:border-r sm:border-line">
          <p className="px-2 pb-2 text-[11px] font-medium tracking-wide text-muted uppercase">Folders</p>
          <ul className="flex flex-col gap-1">
            {collections.map((collection) => {
              const items = filesByFolder[collection.id]
              return (
                <li key={collection.id}>
                  <Link
                    to={`/library/${collection.id}`}
                    className={
                      collection.id === activeId
                        ? 'block rounded-lg bg-paper-raised px-2 py-2 text-sm'
                        : 'block rounded-lg px-2 py-2 text-sm text-muted hover:bg-paper-raised hover:text-ink'
                    }
                  >
                    {collection.label}
                    {items ? ` (${matchingCount(items, sources)})` : ''}
                  </Link>
                </li>
              )
            })}
          </ul>
        </aside>
      ) : null}
      {showFiles ? (
        <div className="min-w-0 flex-1 overflow-auto p-4">
          {breakpoint === 'mobile' ? (
            <Link to="/library" className="mb-3 inline-block text-sm text-accent">
              All folders
            </Link>
          ) : null}
          {activeError && !files ? <p className="text-sm text-danger">{activeError}</p> : null}
          {activeId && !files && !activeError ? <p className="text-sm text-muted">Loading files…</p> : null}
          {files && visible.length === 0 ? (
            <p className="text-sm text-muted">Nothing in this folder matches the selected sources.</p>
          ) : null}
          <ul className="mx-auto flex max-w-2xl flex-col gap-2">
            {visible.map((file) => {
              const Card = sourceRegistry[file.source].Card
              return (
                <li key={file.id}>
                  <Card
                    title={file.title}
                    suffix={fileSuffix(file.source_id)}
                    meta={new Date(file.updated_at).toLocaleDateString()}
                    selected={selection?.docId === file.id}
                    onOpen={() =>
                      openDocument({ docId: file.id, title: file.title, kind: file.source })
                    }
                  />
                </li>
              )
            })}
          </ul>
        </div>
      ) : null}
    </div>
  )
}

function matchingCount(items: LibraryFile[], sources: LibraryFile['source'][]): number {
  return items.filter((file) => sources.includes(file.source)).length
}

function fileSuffix(sourceId: string): string | undefined {
  const name = sourceId.split('/').pop() ?? ''
  const dot = name.lastIndexOf('.')
  if (dot <= 0 || dot === name.length - 1) return undefined
  return name.slice(dot).toLowerCase()
}

function EmptyLibrary({ onAdded }: { onAdded: () => void }) {
  return (
    <div className="mx-auto flex max-w-xl flex-1 flex-col justify-center gap-5 px-6 py-10">
      <div>
        <p className="font-serif text-3xl">No folders yet.</p>
        <p className="mt-3 text-muted">
          Point owlet at a directory on the computer it runs on. Type the path: the browser
          cannot pick a folder for it.
        </p>
      </div>
      <AddFolderForm onAdded={onAdded} />
    </div>
  )
}
