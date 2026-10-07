import { useEffect, useState } from 'react'
import type { ViewerProps } from '@/components/cards/registry'
import { ApiError, getDocument } from '@/lib/api'
import { cn } from '@/lib/cn'
import type { PreviewBlock } from '@/lib/types'

const prose = 'font-serif text-[15px] leading-relaxed'

export function DocxViewer({ docId, title }: ViewerProps) {
  const [blocks, setBlocks] = useState<PreviewBlock[] | null>(null)
  const [fallback, setFallback] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setBlocks(null)
    setFallback(null)
    setError(null)
    getDocument(docId)
      .then((preview) => {
        if (cancelled) return
        if (preview.blocks.length > 0) {
          setBlocks(preview.blocks)
          return
        }
        setFallback(preview.pages.map((page) => page.text).join('\n\n'))
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(reason instanceof ApiError ? reason.message : 'Could not read this document')
        }
      })
    return () => {
      cancelled = true
    }
  }, [docId])

  return (
    <article className="min-h-0 flex-1 overflow-auto px-5 py-5">
      <h2 className="font-serif text-2xl">{title}</h2>
      {error ? <p className="mt-3 text-sm text-danger">{error}</p> : null}
      {blocks == null && fallback == null && !error ? <p className={cn('mt-4', prose)}>Reading…</p> : null}
      {blocks ? (
        <div className="mt-5 flex flex-col gap-3">
          {blocks.map((block, index) => (
            <DocxBlock key={index} block={block} />
          ))}
        </div>
      ) : null}
      {fallback != null ? <pre className={cn('mt-4 whitespace-pre-wrap', prose)}>{fallback}</pre> : null}
    </article>
  )
}

function DocxBlock({ block }: { block: PreviewBlock }) {
  if (block.kind === 'heading') return <DocxHeading level={block.level} text={block.text} />
  if (block.kind === 'list') return <DocxList ordered={block.ordered} items={block.items} />
  if (block.kind === 'table') return <DocxTable rows={block.rows} />
  return <p className={prose}>{block.text}</p>
}

function DocxHeading({ level, text }: { level: number; text: string }) {
  if (level <= 1) return <h2 className="font-serif text-2xl">{text}</h2>
  if (level === 2) return <h3 className="font-serif text-xl">{text}</h3>
  return <h4 className="font-serif text-lg font-semibold">{text}</h4>
}

function DocxList({ ordered, items }: { ordered: boolean; items: string[] }) {
  const List = ordered ? 'ol' : 'ul'
  return (
    <List className={cn('flex flex-col gap-1 pl-5', prose, ordered ? 'list-decimal' : 'list-disc')}>
      {items.map((item, index) => (
        <li key={index}>{item}</li>
      ))}
    </List>
  )
}

function DocxTable({ rows }: { rows: string[][] }) {
  const [head, ...body] = rows
  const header = body.length > 0 ? head : undefined
  const data = header ? body : rows
  return (
    <div className="overflow-x-auto">
      <table className={cn('w-full border-collapse', prose)}>
        {header ? (
          <thead>
            <tr>
              {header.map((cell, index) => (
                <th
                  key={index}
                  className="border border-line bg-paper-raised px-2 py-1.5 text-left font-semibold"
                >
                  {cell}
                </th>
              ))}
            </tr>
          </thead>
        ) : null}
        <tbody>
          {data.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, cellIndex) => (
                <td key={cellIndex} className="border border-line px-2 py-1.5 align-top">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
