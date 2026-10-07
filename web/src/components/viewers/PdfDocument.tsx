import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Minus, Plus } from 'lucide-react'
import { documentUrl } from '@/lib/api'
import { loadPdf, type PDFDocumentProxy } from '@/lib/pdf'
import type { BBox } from '@/lib/types'
import { PdfPage } from '@/components/viewers/PdfPage'

const GUTTER = 24
const ZOOM_STEP = 0.25
const ZOOM_MIN = 0.5
const ZOOM_MAX = 3

/**
 * Continuous page canvas. We render the PDF ourselves rather than handing the
 * file to the browser's plugin because a citation has to be drawn on the page,
 * and an iframe gives us nowhere to put the box.
 */
export function PdfDocument({
  docId,
  page,
  bboxes,
}: {
  docId: string
  page: number
  bboxes: BBox[]
}) {
  const scroller = useRef<HTMLDivElement>(null)
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null)
  const [ratios, setRatios] = useState<number[]>([])
  const [available, setAvailable] = useState(0)
  const [zoom, setZoom] = useState(1)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setDoc(null)
    setRatios([])
    setError(null)
    const { promise, cancel } = loadPdf(documentUrl(docId, 'file'))
    void promise
      .then(async (pdf) => {
        // Measure every page up front: the scroll position of a cited page is
        // only correct once the pages above it have their real height.
        const shapes = await Promise.all(
          Array.from({ length: pdf.numPages }, async (_, index) => {
            const found = await pdf.getPage(index + 1)
            const viewport = found.getViewport({ scale: 1 })
            return viewport.height / viewport.width
          }),
        )
        if (cancelled) return
        setRatios(shapes)
        setDoc(pdf)
      })
      .catch(() => {
        if (!cancelled) setError('Could not render this PDF.')
      })
    return () => {
      cancelled = true
      cancel()
    }
  }, [docId])

  useEffect(() => {
    const element = scroller.current
    if (!element) return
    const observer = new ResizeObserver(([entry]) => {
      setAvailable(entry.contentRect.width - GUTTER)
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  const width = Math.max(0, Math.round(available * zoom))

  useEffect(() => {
    if (!doc || width <= 0) return
    const element = scroller.current
    const target = element?.querySelector(`[data-page="${page}"]`)
    if (!element || !(target instanceof HTMLElement)) return
    element.scrollTo({ top: target.offsetTop - 8 })
    // `ratios` is a dependency because the heights above the target decide
    // where it sits; scrolling before they land would miss.
  }, [doc, page, width, ratios])

  if (error) return <p className="px-4 py-3 text-sm text-danger">{error}</p>

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-1 border-b border-line px-3 py-1.5">
        <Zoom label="Zoom out" onClick={() => setZoom((v) => Math.max(ZOOM_MIN, v - ZOOM_STEP))}>
          <Minus size={15} />
        </Zoom>
        <button
          type="button"
          onClick={() => setZoom(1)}
          className="min-w-14 rounded-full px-2 py-1 text-xs tabular-nums text-muted hover:bg-paper"
        >
          {Math.round(zoom * 100)}%
        </button>
        <Zoom label="Zoom in" onClick={() => setZoom((v) => Math.min(ZOOM_MAX, v + ZOOM_STEP))}>
          <Plus size={15} />
        </Zoom>
      </div>
      <div ref={scroller} className="relative min-h-0 flex-1 overflow-auto bg-paper-raised p-3">
        {doc
          ? ratios.map((ratio, index) => (
              <PdfPage
                key={index + 1}
                doc={doc}
                number={index + 1}
                width={width}
                ratio={ratio}
                highlights={bboxes.filter((box) => box.page === index + 1)}
              />
            ))
          : <p className="px-1 text-sm text-muted">Opening…</p>}
      </div>
    </div>
  )
}

function Zoom({
  label,
  onClick,
  children,
}: {
  label: string
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      className="rounded-full p-1.5 text-muted hover:bg-paper"
    >
      {children}
    </button>
  )
}
