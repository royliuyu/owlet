import { useCallback, useEffect, useState, type FormEvent } from 'react'
import {
  ApiError,
  cancelGoogleAttempt,
  disconnectGoogleAccount,
  getGoogle,
  getGoogleAttempt,
  notifyAccountsChanged,
  saveGoogleClient,
  setGoogleCalendar,
  startGoogleSignIn,
  syncGoogleAccount,
} from '@/lib/api'
import type { GoogleAccount, GoogleOverview } from '@/lib/types'

type Waiting = {
  id: string
  onServer: boolean
  url: string
  showLink: boolean
  adding: boolean
}

export function GoogleAccounts() {
  const [overview, setOverview] = useState<GoogleOverview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [waiting, setWaiting] = useState<Waiting | null>(null)
  const [editingClient, setEditingClient] = useState(false)
  const [syncingId, setSyncingId] = useState<string | null>(null)

  const reload = useCallback(() => {
    getGoogle()
      .then((next) => {
        setOverview(next)
        setError(null)
      })
      .catch((reason: unknown) => {
        setError(reason instanceof ApiError ? reason.message : 'Could not load Google accounts')
      })
  }, [])

  useEffect(reload, [reload])

  useEffect(() => {
    if (!waiting) return
    let stopped = false
    const timer = window.setInterval(() => {
      getGoogleAttempt(waiting.id)
        .then((next) => {
          if (stopped || next.status === 'pending') return
          window.clearInterval(timer)
          setWaiting(null)
          setNote(next.message || signInNote(next.status, next.email))
          if (next.status === 'connected') {
            reload()
            notifyAccountsChanged()
          }
        })
        .catch((reason: unknown) => {
          if (stopped) return
          setWaiting(null)
          setError(reason instanceof ApiError ? reason.message : 'Sign-in did not finish')
        })
    }, 1000)
    return () => {
      stopped = true
      window.clearInterval(timer)
    }
  }, [reload, waiting])

  function begin(product: 'calendar' | 'mail', accountId?: string) {
    if (busy || waiting) return
    setBusy(true)
    setError(null)
    setNote(null)
    startGoogleSignIn({ product, account_id: accountId })
      .then((started) => {
        const showLink = started.opened_on_server && !started.opened_locally
        setWaiting({
          id: started.attempt_id,
          onServer: started.opened_on_server,
          url: started.url,
          showLink,
          adding: product === 'mail' || accountId === undefined,
        })
        if (!started.opened_on_server) {
          const popup = window.open(started.url, '_blank', 'noopener')
          if (!popup) {
            setWaiting((current) => (current ? { ...current, showLink: true } : current))
          }
        }
      })
      .catch((reason: unknown) => {
        setError(reason instanceof ApiError ? reason.message : 'Could not start sign-in')
      })
      .finally(() => setBusy(false))
  }

  function stopWaiting() {
    if (!waiting) return
    const id = waiting.id
    const adding = waiting.adding
    setWaiting(null)
    cancelGoogleAttempt(id)
      .then((next) => {
        if (next.status === 'connected') {
          setNote(next.message || signInNote(next.status, next.email))
          reload()
          notifyAccountsChanged()
          return
        }
        if (adding) setNote('Adding was stopped.')
      })
      .catch((reason: unknown) => {
        setError(reason instanceof ApiError ? reason.message : 'Could not stop sign-in')
      })
  }

  function run(work: Promise<unknown>, fallback: string) {
    setError(null)
    work
      .then(() => {
        reload()
        notifyAccountsChanged()
      })
      .catch((reason: unknown) => {
        setError(reason instanceof ApiError ? reason.message : fallback)
        reload()
      })
  }

  const accounts = overview?.accounts ?? []
  const configured = overview?.configured ?? false

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="font-serif text-2xl">Google</h2>
        <p className="mt-1 text-sm text-muted">
          Separate from folders. Owlet reads calendars on the account you choose and cannot change
          them. Calendars update about every 15 minutes. Mail can be added on the same account
          later.
        </p>
      </div>
      {error ? <p className="text-sm text-danger">{error}</p> : null}
      {note ? <p className="text-sm text-muted">{note}</p> : null}
      {waiting ? (
        <div className="rounded-xl border border-line bg-paper px-3 py-3 text-sm">
          <p>{waitingLine(waiting)}</p>
          {waiting.showLink ? (
            <a
              href={waiting.url}
              target="_blank"
              rel="noreferrer"
              className="mt-2 inline-block text-accent"
            >
              {waiting.onServer
                ? 'Open this link on the computer running owlet'
                : 'Open the sign-in window'}
            </a>
          ) : null}
          <button
            type="button"
            className="mt-2 block text-muted hover:text-ink"
            onClick={stopWaiting}
          >
            {waiting.adding ? 'Stop adding' : 'Stop waiting'}
          </button>
        </div>
      ) : null}
      {overview && accounts.length === 0 ? (
        <p className="text-sm text-muted">No Google account yet.</p>
      ) : null}
      {accounts.length > 0 ? (
        <ul className="flex flex-col gap-3">
          {accounts.map((account) => (
            <AccountCard
              key={account.id}
              account={account}
              disabled={Boolean(waiting) || busy}
              onCalendar={(calendarId, enabled) =>
                run(
                  setGoogleCalendar(account.id, { calendar_id: calendarId, enabled }),
                  'Could not update the calendar',
                )
              }
              syncing={syncingId === account.id}
              onSync={() => {
                setSyncingId(account.id)
                setError(null)
                syncGoogleAccount(account.id)
                  .then(() => {
                    reload()
                    notifyAccountsChanged()
                  })
                  .catch((reason: unknown) => {
                    setError(
                      reason instanceof ApiError ? reason.message : 'Could not refresh calendars',
                    )
                    reload()
                  })
                  .finally(() => setSyncingId(null))
              }}
              onMail={() => begin('mail', account.id)}
              onReconnect={() => begin('calendar', account.id)}
              onDisconnect={() => {
                const ok = window.confirm(
                  'This removes the local copy of this account. Google is unchanged.',
                )
                if (!ok) return
                run(disconnectGoogleAccount(account.id), 'Could not disconnect the account')
              }}
            />
          ))}
        </ul>
      ) : null}
      {overview?.account_email ? (
        <p className="text-sm">
          Google signs in as <span className="font-medium">{overview.account_email}</span>.
        </p>
      ) : null}
      {overview && (!configured || editingClient) ? (
        <ClientForm
          clientId={overview.client_id}
          accountEmail={overview.account_email}
          redirectUris={overview.redirect_uris}
          onSaved={(next) => {
            setOverview(next)
            setEditingClient(false)
            setError(null)
          }}
          onError={setError}
        />
      ) : null}
      {configured && !editingClient ? (
        <button
          type="button"
          className="self-start text-sm text-muted hover:text-ink"
          onClick={() => setEditingClient(true)}
        >
          Edit client
        </button>
      ) : null}
      <button
        type="button"
        disabled={!configured || busy || Boolean(waiting)}
        onClick={() => begin('calendar')}
        className="self-start rounded-full bg-ink px-4 py-2 text-sm text-paper disabled:opacity-40"
      >
        {accounts.length === 0 ? 'Connect Google account' : 'Add another Google account'}
      </button>
    </div>
  )
}

function ClientForm({
  clientId,
  accountEmail,
  redirectUris,
  onSaved,
  onError,
}: {
  clientId: string
  accountEmail: string
  redirectUris: string[]
  onSaved: (overview: GoogleOverview) => void
  onError: (message: string) => void
}) {
  const [email, setEmail] = useState(accountEmail)
  const [id, setId] = useState(clientId)
  const [secret, setSecret] = useState('')
  const [saving, setSaving] = useState(false)

  function submit(event: FormEvent) {
    event.preventDefault()
    if (saving || !id.trim() || !email.trim()) return
    setSaving(true)
    saveGoogleClient({
      client_id: id.trim(),
      client_secret: secret.trim() || undefined,
      account_email: email.trim(),
    })
      .then(onSaved)
      .catch((reason: unknown) => {
        onError(reason instanceof ApiError ? reason.message : 'Could not save the Google client')
      })
      .finally(() => setSaving(false))
  }

  return (
    <form className="flex flex-col gap-3" onSubmit={submit}>
      <div className="flex flex-col gap-1">
        <label htmlFor="google-account-email" className="text-sm font-medium">
          Google account
        </label>
        <input
          id="google-account-email"
          type="email"
          value={email}
          autoComplete="email"
          placeholder="you@gmail.com"
          onChange={(event) => setEmail(event.target.value)}
          className="rounded-xl border border-line bg-paper px-3 py-3 text-base outline-none focus:border-accent"
        />
        <p className="text-sm text-muted">
          The address Google opens. Sign-in on the next screen uses this account.
        </p>
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="google-client-id" className="text-sm font-medium">
          OAuth client ID
        </label>
        <input
          id="google-client-id"
          value={id}
          spellCheck={false}
          autoComplete="off"
          placeholder="123456789012-abc.apps.googleusercontent.com"
          onChange={(event) => setId(event.target.value)}
          className="rounded-xl border border-line bg-paper px-3 py-3 text-base outline-none focus:border-accent"
        />
        <p className="text-sm text-muted">
          Not the address above. Copy the OAuth client ID from Google Cloud. It ends with
          .apps.googleusercontent.com.
        </p>
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="google-client-secret" className="text-sm font-medium">
          Client secret <span className="font-normal text-muted">(optional)</span>
        </label>
        <input
          id="google-client-secret"
          type="password"
          value={secret}
          autoComplete="off"
          onChange={(event) => setSecret(event.target.value)}
          className="rounded-xl border border-line bg-paper px-3 py-3 text-base outline-none focus:border-accent"
        />
      </div>
      {redirectUris.length > 0 ? (
        <div className="text-sm text-muted">
          <p>Register these redirect URIs on the Google client:</p>
          <ul className="mt-1 flex flex-col gap-1">
            {redirectUris.map((uri) => (
              <li key={uri} className="break-all font-mono text-xs">
                {uri}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <button
        type="submit"
        disabled={saving || !id.trim() || !email.trim()}
        className="self-start rounded-full bg-ink px-4 py-2 text-sm text-paper disabled:opacity-40"
      >
        {saving ? 'Saving…' : 'Save'}
      </button>
    </form>
  )
}

function AccountCard({
  account,
  disabled,
  syncing,
  onCalendar,
  onSync,
  onMail,
  onReconnect,
  onDisconnect,
}: {
  account: GoogleAccount
  disabled: boolean
  syncing: boolean
  onCalendar: (calendarId: string, enabled: boolean) => void
  onSync: () => void
  onMail: () => void
  onReconnect: () => void
  onDisconnect: () => void
}) {
  const mail = account.scopes.some((scope) => scope.endsWith('/gmail.readonly'))
  const hasCalendar = account.scopes.some((scope) => scope.endsWith('/calendar.readonly'))
  const expired = account.status === 'reconnect'
  return (
    <li className="flex flex-col gap-3 rounded-xl border border-line bg-paper px-3 py-3">
      <div>
        <p className="font-medium">{account.email}</p>
        <p className="mt-1 text-sm text-muted">{statusLine(account)}</p>
      </div>
      <div>
        <p className="text-[11px] font-medium tracking-wide text-muted uppercase">Calendar</p>
        {!hasCalendar ? (
          <p className="mt-2 text-sm text-muted">
            Calendar access was not granted for this account.
          </p>
        ) : account.calendars.length === 0 ? (
          <p className="mt-2 text-sm text-muted">No calendars returned yet.</p>
        ) : (
          <ul className="mt-2 flex flex-col gap-1">
            {account.calendars.map((calendar) => {
              const held = Boolean(calendar.held_by)
              return (
                <li key={calendar.calendar_id}>
                  <label className="flex items-start gap-2 py-1 text-sm">
                    <input
                      type="checkbox"
                      className="mt-1 size-4 accent-ink"
                      checked={calendar.enabled && !held}
                      disabled={disabled || held}
                      aria-label={`Read ${calendar.summary}`}
                      onChange={(event) => onCalendar(calendar.calendar_id, event.target.checked)}
                    />
                    <span className="min-w-0 flex-1">
                      <span className={calendar.enabled && !held ? '' : 'text-muted'}>
                        {calendar.summary}
                      </span>
                      {calendar.primary ? (
                        <span className="ml-2 text-muted">primary</span>
                      ) : null}
                      {held ? (
                        <span className="mt-0.5 block text-muted">
                          Already included from {calendar.held_by}
                        </span>
                      ) : null}
                    </span>
                  </label>
                </li>
              )
            })}
          </ul>
        )}
        {hasCalendar && account.calendars.some((item) => item.enabled && !item.held_by) ? (
          <p className="mt-2 text-sm text-muted">
            {account.event_count > 0
              ? `${account.event_count} events saved. Today shows the ones for this day.`
              : 'Sync to load events onto Today.'}
          </p>
        ) : null}
      </div>
      {mail ? (
        <p className="text-sm text-muted">Mail is included. Owlet can read it and cannot send.</p>
      ) : (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <button
            type="button"
            disabled={disabled || expired}
            onClick={onMail}
            className="text-sm text-ink disabled:opacity-40"
          >
            Add mail
          </button>
          <span className="text-sm text-muted">Reads mail on this account. Cannot send.</span>
        </div>
      )}
      <div className="flex flex-wrap gap-x-4 gap-y-2 text-sm">
        {!hasCalendar ? (
          <button type="button" disabled={disabled} onClick={onReconnect} className="text-ink">
            Allow calendar
          </button>
        ) : expired ? (
          <button type="button" disabled={disabled} onClick={onReconnect} className="text-ink">
            Reconnect
          </button>
        ) : (
          <button
            type="button"
            disabled={disabled || syncing}
            onClick={onSync}
            className="text-muted hover:text-ink disabled:opacity-40"
          >
            {syncing ? 'Syncing…' : 'Sync now'}
          </button>
        )}
        <button type="button" disabled={disabled} onClick={onDisconnect} className="text-muted hover:text-danger">
          Disconnect
        </button>
      </div>
    </li>
  )
}

function statusLine(account: GoogleAccount): string {
  if (account.status === 'reconnect') return 'Sign-in expired'
  if (!account.last_sync_at) return 'Connected'
  const then = new Date(account.last_sync_at).getTime()
  if (Number.isNaN(then)) return 'Connected'
  const minutes = Math.round((Date.now() - then) / 60000)
  if (minutes < 1) return 'Updated just now'
  if (minutes < 60) return `Updated ${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 36) return `Updated ${hours} hr ago`
  return `Updated ${new Date(account.last_sync_at).toLocaleDateString()}`
}

function waitingLine(waiting: Waiting): string {
  const where = waiting.onServer
    ? 'Finish sign-in on the computer running owlet. This page updates when it completes.'
    : 'Finish sign-in in the browser window. This page updates when it completes.'
  if (!waiting.adding) return where
  return `Adding a Google account. ${where}`
}

function signInNote(status: string, email: string | null): string {
  if (status === 'connected') return email ? `Connected ${email}.` : 'Connected.'
  if (status === 'cancelled') return 'Sign-in was cancelled.'
  if (status === 'expired') return 'That sign-in took too long. Start again.'
  if (status === 'mismatch') return 'That was a different Google account. Nothing was changed.'
  return 'Sign-in did not finish.'
}
