import { useState } from 'react'
import { ChevronRight } from 'lucide-react'
import { sourceRegistry } from '@/components/cards/registry'
import { ApiError, confirmAction } from '@/lib/api'
import { MarkdownText, ViewSwitch } from '@/components/markdown/MarkdownText'
import { cn } from '@/lib/cn'
import type { BBox, Block, Citation, OpenDocument } from '@/lib/types'

type ToolBlock = Extract<Block, { type: 'tool' }>

export function BlockRenderer({
  blocks,
  onOpen,
}: {
  blocks: Block[]
  onOpen: (document: OpenDocument) => void
}) {
  const [raw, setRaw] = useState(false)
  const tools = blocks.filter((block): block is ToolBlock => block.type === 'tool')
  const citations = blocks.find((block) => block.type === 'citations')
  const items = citations?.type === 'citations' ? citations.items : []
  const foldAt = blocks.findIndex((block) => block.type === 'tool' || block.type === 'citations')
  const hasText = blocks.some((block) => block.type === 'text' && block.content.trim() !== '')

  return (
    <div className="flex flex-col gap-3">
      {blocks.map((block, index) => {
        if (block.type === 'tool' || block.type === 'citations') {
          if (index !== foldAt) return null
          return <SourcesFold key="sources" tools={tools} items={items} onOpen={onOpen} />
        }
        if (block.type === 'text') {
          return (
            <TextBlock key={index} content={block.content} raw={raw} items={items} onOpen={onOpen} />
          )
        }
        if (block.type === 'action') {
          return <ActionCard key={block.action_id} block={block} />
        }
        return (
          <p
            key={index}
            className="rounded-xl border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger"
          >
            {block.message}
          </p>
        )
      })}
      {hasText ? <ViewSwitch raw={raw} onChange={setRaw} /> : null}
    </div>
  )
}

function SourcesFold({
  tools,
  items,
  onOpen,
}: {
  tools: ToolBlock[]
  items: Citation[]
  onOpen: (document: OpenDocument) => void
}) {
  const [open, setOpen] = useState(false)
  const running = stillRunning(tools)
  const count = items.length
  const label = sourceLabel(running, count, tools.at(-1)?.summary)

  return (
    <div>
      <button
        type="button"
        disabled={count === 0}
        aria-expanded={count > 0 ? open : undefined}
        onClick={() => setOpen((value) => !value)}
        className="inline-flex items-center gap-1 rounded-full px-1.5 py-1 text-sm text-muted hover:bg-paper-raised disabled:opacity-100"
      >
        {count > 0 ? (
          <ChevronRight size={14} className={cn('shrink-0 transition-transform', open && 'rotate-90')} />
        ) : (
          <span className="mx-0.5 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-muted" />
        )}
        {label}
      </button>
      {open && count > 0 ? (
        <ul className="mt-1 ml-2 flex flex-col border-l border-line">
          {items.map((item) => (
            <li key={item.n}>
              <SourceRow item={item} onOpen={onOpen} />
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

function stillRunning(tools: ToolBlock[]): boolean {
  const latest = new Map<string, ToolBlock>()
  for (const tool of tools) latest.set(tool.tool, tool)
  return [...latest.values()].some((tool) => tool.status === 'running')
}

function sourceLabel(running: boolean, count: number, fallback: string | undefined): string {
  if (running && count === 0) return fallback ?? 'Searching the library…'
  if (running) return `Searching… ${count} so far`
  if (count === 1) return '1 source'
  if (count > 1) return `${count} sources`
  return fallback ?? 'Search finished'
}

function SourceRow({
  item,
  onOpen,
}: {
  item: Citation
  onOpen: (document: OpenDocument) => void
}) {
  const page = pageOf(item.locator)
  const where = page ? `p. ${page}` : sourceRegistry[item.kind].label
  return (
    <button
      type="button"
      onClick={() => onOpen(openFromCitation(item))}
      className="flex w-full items-baseline gap-2 rounded-r-lg px-2 py-1.5 text-left hover:bg-paper-raised"
    >
      <span className="inline-flex h-5 min-w-5 shrink-0 items-center justify-center rounded bg-accent-soft px-1 text-[11px] font-semibold text-accent">
        {item.n}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm">{item.title}</span>
        {item.snippet ? <span className="block truncate text-xs text-muted">{item.snippet}</span> : null}
      </span>
      <span className="shrink-0 text-xs text-muted">{where}</span>
    </button>
  )
}

function TextBlock({
  content,
  raw,
  items,
  onOpen,
}: {
  content: string
  raw: boolean
  items: Citation[]
  onOpen: (document: OpenDocument) => void
}) {
  return (
    <MarkdownText
      content={content}
      raw={raw}
      renderCite={(n) => {
        const citation = items.find((item) => item.n === n)
        if (!citation) return <span>[{n}]</span>
        return (
          <button
            type="button"
            className="mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded bg-accent-soft px-1 align-super font-sans text-[11px] font-semibold text-accent"
            onClick={() => onOpen(openFromCitation(citation))}
          >
            {n}
          </button>
        )
      }}
    />
  )
}

function ActionCard({
  block,
}: {
  block: Extract<Block, { type: 'action' }>
}) {
  const [pending, setPending] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  return (
    <div className="rounded-xl border border-line bg-paper-raised px-3 py-3">
      <p className="text-[11px] font-medium tracking-wide text-muted uppercase">Needs confirmation</p>
      <p className="mt-1 font-medium">{block.kind.replaceAll('_', ' ')}</p>
      <pre className="mt-2 overflow-auto text-xs text-muted">{JSON.stringify(block.params, null, 2)}</pre>
      <button
        type="button"
        disabled={pending}
        className="mt-3 rounded-full bg-ink px-3 py-1.5 text-sm text-paper disabled:opacity-50"
        onClick={() => {
          setPending(true)
          confirmAction(block.action_id)
            .then(() => setNote('Confirmed.'))
            .catch((reason: unknown) => {
              setNote(reason instanceof ApiError ? reason.message : 'Could not confirm')
            })
            .finally(() => setPending(false))
        }}
      >
        Confirm
      </button>
      {note ? <p className="mt-2 text-sm text-muted">{note}</p> : null}
    </div>
  )
}

function openFromCitation(item: Citation): OpenDocument {
  return {
    docId: item.doc_id,
    title: item.title,
    kind: item.kind,
    page: pageOf(item.locator),
    snippet: item.snippet,
    bboxes: boxesOf(item.locator),
  }
}

function pageOf(locator: Record<string, unknown>): number | undefined {
  return typeof locator.page === 'number' ? locator.page : undefined
}

function boxesOf(locator: Record<string, unknown>): BBox[] | undefined {
  return Array.isArray(locator.bboxes) ? (locator.bboxes as BBox[]) : undefined
}
