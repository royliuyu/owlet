import { useCallback, useEffect, useRef, useState } from 'react'
import { AddFolderForm } from '@/components/library/AddFolderForm'
import { FolderList } from '@/components/library/FolderList'
import { GoogleAccounts } from '@/components/library/GoogleAccounts'
import { IndexPanel } from '@/components/library/IndexPanel'
import { ApiError, listCollections, openSession, readToken, writeToken } from '@/lib/api'
import type { Collection } from '@/lib/types'

const panel = 'rounded-2xl border border-line bg-paper-raised p-5 shadow-[0_1px_2px_rgba(28,25,22,0.05)]'

export function SettingsView() {
  const [token, setToken] = useState(readToken)
  const [note, setNote] = useState<string | null>(null)
  const [collections, setCollections] = useState<Collection[]>([])
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [indexRevision, setIndexRevision] = useState(0)
  const listRequest = useRef(0)

  const reload = useCallback(() => {
    const request = ++listRequest.current
    listCollections()
      .then((items) => {
        if (request !== listRequest.current) return
        setCollections(items)
        setError(null)
      })
      .catch((reason: unknown) => {
        if (request !== listRequest.current) return
        setError(reason instanceof ApiError ? reason.message : 'Could not load settings')
      })
  }, [])

  useEffect(reload, [reload, note])

  function removed(collection: Collection) {
    setCollections((current) => current.filter((item) => item.id !== collection.id))
    setError(null)
    setNotice(`Removed ${collection.label}.`)
    setIndexRevision((value) => value + 1)
    reload()
  }

  function removeFailed(collection: Collection, message: string) {
    const request = ++listRequest.current
    listCollections()
      .then((items) => {
        if (request !== listRequest.current) return
        setCollections(items)
        if (items.some((item) => item.id === collection.id)) {
          setNotice(null)
          setError(message)
          return
        }
        setError(null)
        setNotice(`Removed ${collection.label}.`)
        setIndexRevision((value) => value + 1)
      })
      .catch(() => {
        if (request !== listRequest.current) return
        setError(message)
      })
  }

  return (
    <section className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-8 self-center overflow-auto px-6 py-8">
      <section className={panel}>
        <h2 className="font-serif text-2xl">Access token</h2>
        <p className="mt-1 text-sm text-muted">
          Checked on every API call, including the PDF reader.
        </p>
        <form
          className="mt-4 flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault()
            writeToken(token.trim())
            openSession(token.trim())
              .then(() => setNote(token.trim() ? 'Token saved.' : 'Token cleared.'))
              .catch((reason: unknown) => {
                setNote(reason instanceof ApiError ? reason.message : 'Could not save the token')
              })
          }}
        >
          <label htmlFor="token" className="sr-only">
            Access token
          </label>
          <input
            id="token"
            type="password"
            autoComplete="current-password"
            value={token}
            onChange={(event) => setToken(event.target.value)}
            className="rounded-xl border border-line bg-paper px-3 py-3 text-base outline-none focus:border-accent"
          />
          <button type="submit" className="self-start rounded-full bg-ink px-4 py-2 text-sm text-paper">
            Save token
          </button>
          {note ? <p className="text-sm text-muted">{note}</p> : null}
        </form>
      </section>
      <section className={panel}>
        <h2 className="font-serif text-2xl">Folders</h2>
        <div className="mt-4 flex flex-col gap-4">
          {notice ? <p className="text-sm">{notice}</p> : null}
          {error ? <p className="text-sm text-danger">{error}</p> : null}
          {collections.length === 0 ? (
            <p className="text-sm text-muted">None yet. Add one below.</p>
          ) : (
            <FolderList
              collections={collections}
              onChanged={reload}
              onRemoved={removed}
              onRemoveFailed={removeFailed}
            />
          )}
          <AddFolderForm
            onAdded={() => {
              setNotice(null)
              reload()
            }}
          />
        </div>
      </section>
      <section className={panel}>
        <IndexPanel refreshKey={indexRevision} />
      </section>
      <section className={panel}>
        <GoogleAccounts />
      </section>
    </section>
  )
}
