import { useEffect, useState } from 'react'
import type { ViewerProps } from '@/components/cards/registry'
import { MarkdownText, ViewSwitch } from '@/components/markdown/MarkdownText'
import { ApiError, getDocument } from '@/lib/api'
import { cn } from '@/lib/cn'
import type { Document } from '@/lib/types'

const readerProse = 'font-serif text-[15px] leading-relaxed'

/** Plain text until a sanitizer is added. Mail and notes must not become raw HTML. */
export function MarkdownViewer({ docId, title }: ViewerProps) {
  const [text, setText] = useState<string | null>(null)
  const [markdown, setMarkdown] = useState(false)
  const [raw, setRaw] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setText(null)
    setMarkdown(false)
    setRaw(false)
    setError(null)
    getDocument(docId)
      .then((preview) => {
        if (cancelled) return
        setText(preview.pages.map((page) => page.text).join('\n\n'))
        setMarkdown(isMarkdown(preview.document))
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
    <article className="flex min-h-0 flex-1 flex-col">
      {markdown ? (
        <div className="border-b border-line px-4 py-2">
          <ViewSwitch raw={raw} onChange={setRaw} />
        </div>
      ) : null}
      <div className="min-h-0 flex-1 overflow-auto px-4 py-4">
        <h2 className="font-serif text-2xl">{title}</h2>
        {error ? <p className="mt-3 text-sm text-danger">{error}</p> : null}
        {text == null && !error ? <p className={cn('mt-4', readerProse)}>Reading…</p> : null}
        {text != null && markdown ? (
          <div className="mt-4">
            <MarkdownText content={text} raw={raw} prose={readerProse} />
          </div>
        ) : null}
        {text != null && !markdown ? (
          <pre className={cn('mt-4 whitespace-pre-wrap', readerProse)}>{text}</pre>
        ) : null}
      </div>
    </article>
  )
}

function isMarkdown(document: Document): boolean {
  if (document.extra.format === 'markdown') return true
  if (document.extra.media_type === 'text/markdown') return true
  return /\.(md|markdown)$/i.test(`${document.source_id} ${document.uri}`)
}
