import { Suspense, lazy, useEffect, useState } from 'react'
import { ApiError, getDocument } from '@/lib/api'
import type { PagePreview } from '@/lib/types'
import type { ViewerProps } from '@/components/cards/registry'
import { cn } from '@/lib/cn'

// pdf.js is about as large as the rest of the app, and most sessions never
// open a paper, so it arrives with the first one.
const PdfDocument = lazy(async () => ({
  default: (await import('@/components/viewers/PdfDocument')).PdfDocument,
}))

export function PdfViewer({ docId, page, bboxes }: ViewerProps) {
  const [mode, setMode] = useState<'original' | 'text'>('original')
  const [pages, setPages] = useState<PagePreview[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const target = page && page > 0 ? page : 1

  useEffect(() => {
    let cancelled = false
    setPages(null)
    setError(null)
    getDocument(docId)
      .then((preview) => {
        if (!cancelled) setPages(preview.pages)
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof ApiError ? reason.message : 'Could not read this PDF')
      })
    return () => {
      cancelled = true
    }
  }, [docId])

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-1 border-b border-line px-3 py-2">
        <ModeButton active={mode === 'original'} onClick={() => setMode('original')}>
          Original
        </ModeButton>
        <ModeButton active={mode === 'text'} onClick={() => setMode('text')}>
          Text
        </ModeButton>
        <span className="ml-auto text-xs text-muted">Page {target}</span>
      </div>
      {error ? <p className="px-4 py-3 text-sm text-danger">{error}</p> : null}
      {mode === 'original' ? (
        <Suspense fallback={<p className="px-4 py-3 text-sm text-muted">Opening…</p>}>
          <PdfDocument docId={docId} page={target} bboxes={bboxes ?? []} />
        </Suspense>
      ) : (
        <div className="min-h-0 flex-1 overflow-auto px-4 py-3">
          {(pages ?? []).map((item) => (
            <article
              key={item.page}
              className={cn(
                'mb-4 rounded-xl border px-3 py-3',
                item.page === target ? 'border-accent bg-accent-soft' : 'border-line',
              )}
            >
              <h3 className="text-[11px] font-medium tracking-wide text-muted uppercase">
                Page {item.page}
              </h3>
              <p className="mt-2 font-serif text-[15px] leading-relaxed whitespace-pre-wrap">
                {item.text || 'This page has no extractable text.'}
              </p>
            </article>
          ))}
          {pages && pages.length === 0 ? (
            <p className="text-sm text-muted">No text could be extracted from this PDF.</p>
          ) : null}
        </div>
      )}
    </div>
  )
}

function ModeButton({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'rounded-full px-3 py-1 text-sm',
        active ? 'bg-ink text-paper' : 'text-muted hover:bg-paper',
      )}
    >
      {children}
    </button>
  )
}
