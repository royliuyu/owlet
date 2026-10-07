import { useEffect, useState, type ReactNode } from 'react'
import { ApiError, getGoogle, getGoogleEvents } from '@/lib/api'
import type { GoogleEvent } from '@/lib/types'

export function TodayView() {
  const [events, setEvents] = useState<GoogleEvent[] | null>(null)
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState<GoogleEvent | null>(null)

  useEffect(() => {
    Promise.all([getGoogleEvents(), getGoogle()])
      .then(([items, overview]) => {
        setEvents(items)
        setConnected(overview.accounts.length > 0)
        setError(null)
      })
      .catch((reason: unknown) => {
        setError(reason instanceof ApiError ? reason.message : 'Could not load today')
      })
  }, [])

  useEffect(() => {
    if (!open) return
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  const today = (events ?? []).filter(isToday)

  return (
    <section className="mx-auto flex w-full max-w-xl flex-1 flex-col px-6 py-10">
      <h2 className="font-serif text-3xl">Today</h2>
      {error ? <p className="mt-3 text-sm text-danger">{error}</p> : null}
      {events === null && !error ? <p className="mt-3 text-muted">Loading the day.</p> : null}
      {events !== null && !connected ? (
        <p className="mt-3 leading-relaxed text-muted">
          Connect a Google account in Settings to show this day’s calendar.
        </p>
      ) : null}
      {events !== null && connected && today.length === 0 ? (
        <p className="mt-3 leading-relaxed text-muted">
          Nothing scheduled today. Calendars update about every 15 minutes.
        </p>
      ) : null}
      {today.length > 0 ? (
        <ul className="mt-6 flex flex-col">
          {today.map((event) => (
            <li key={`${event.calendar}-${event.id}`} className="border-t border-line">
              <button
                type="button"
                className="grid w-full grid-cols-[7.5rem_1fr] items-baseline gap-3 py-3 text-left hover:bg-paper-raised"
                onClick={() => setOpen(event)}
              >
                <span className="text-sm text-muted">
                  {event.all_day ? 'All day' : clock(event)}
                </span>
                <span className="font-medium">{event.summary}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {open ? <EventCard event={open} onClose={() => setOpen(null)} /> : null}
    </section>
  )
}

function EventCard({ event, onClose }: { event: GoogleEvent; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4">
      <button
        type="button"
        className="absolute inset-0 bg-ink/30"
        aria-label="Close event"
        onClick={onClose}
      />
      <article
        role="dialog"
        aria-modal="true"
        aria-labelledby="event-title"
        className="relative flex max-h-[min(36rem,85vh)] w-full max-w-md flex-col overflow-hidden rounded-2xl border border-line bg-paper-raised shadow-xl"
      >
        <header className="flex items-start gap-3 px-5 pt-4">
          <span className="mt-1.5 size-3 shrink-0 rounded-sm bg-accent" aria-hidden="true" />
          <h3 id="event-title" className="min-w-0 flex-1 font-serif text-2xl leading-tight">
            {event.summary}
          </h3>
          <button
            type="button"
            className="rounded-full px-2 py-1 text-lg leading-none text-muted hover:bg-paper hover:text-ink"
            aria-label="Close"
            onClick={onClose}
          >
            ×
          </button>
        </header>
        <div className="overflow-y-auto px-5 pt-3 pb-5">
          <p className="pl-6 text-sm">{when(event)}</p>
          {event.recurrence ? (
            <p className="mt-1 pl-6 text-sm text-muted">{event.recurrence}</p>
          ) : null}
          {event.location ? <p className="mt-4 pl-6 text-sm">{event.location}</p> : null}
          {event.description ? (
            <div className="mt-4 border-t border-line pt-4">
              <p className="whitespace-pre-wrap text-sm leading-relaxed">{linkify(event.description)}</p>
            </div>
          ) : null}
        </div>
      </article>
    </div>
  )
}

function isToday(event: GoogleEvent): boolean {
  const now = new Date()
  if (event.all_day) {
    const day = localDate(now)
    const end = event.end || event.start
    return event.start <= day && day < end
  }
  const start = new Date(event.start)
  return !Number.isNaN(start.getTime()) && sameDay(start, now)
}

function sameDay(left: Date, right: Date): boolean {
  return (
    left.getFullYear() === right.getFullYear() &&
    left.getMonth() === right.getMonth() &&
    left.getDate() === right.getDate()
  )
}

function localDate(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

function clock(event: GoogleEvent): string {
  const start = new Date(event.start)
  const end = new Date(event.end)
  if (Number.isNaN(start.getTime())) return ''
  return span(start, end)
}

function when(event: GoogleEvent): string {
  if (event.all_day) return 'All day'
  const start = new Date(event.start)
  const end = new Date(event.end)
  if (Number.isNaN(start.getTime())) return ''
  const date = start.toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' })
  return `${date} · ${span(start, end)}`
}

function span(start: Date, end: Date): string {
  const startText = start.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  if (Number.isNaN(end.getTime())) return startText
  const endText = end.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  const samePeriod = start.getHours() < 12 === end.getHours() < 12
  if (!samePeriod) return `${startText} – ${endText}`
  return `${startText.replace(/\s*[AP]M$/i, '')} – ${endText}`
}

function linkify(text: string): ReactNode[] {
  const pattern = /https?:\/\/[^\s<>]+/g
  const nodes: ReactNode[] = []
  let last = 0
  for (const match of text.matchAll(pattern)) {
    const index = match.index ?? 0
    if (index > last) nodes.push(text.slice(last, index))
    const raw = match[0]
    const url = raw.replace(/[),.;]+$/, '')
    const trail = raw.slice(url.length)
    nodes.push(
      <a key={index} href={url} target="_blank" rel="noreferrer" className="break-all text-accent">
        {url}
      </a>,
    )
    if (trail) nodes.push(trail)
    last = index + raw.length
  }
  if (last < text.length) nodes.push(text.slice(last))
  return nodes
}
