import { useEffect, useRef, useState } from 'react'
import type { PDFDocumentProxy } from '@/lib/pdf'
import type { BBox } from '@/lib/types'

/** Render a screen ahead so scrolling to a citation never lands on a blank. */
const PRERENDER = '150% 0px'

const MAX_DPR = 2

export function PdfPage({
  doc,
  number,
  width,
  ratio,
  highlights,
}: {
  doc: PDFDocumentProxy
  number: number
  width: number
  ratio: number
  highlights: BBox[]
}) {
  const holder = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const [near, setNear] = useState(false)

  useEffect(() => {
    const element = holder.current
    if (!element) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) setNear(true)
      },
      { rootMargin: PRERENDER },
    )
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (!near || width <= 0) return
    let cancelled = false
    let stop: (() => void) | null = null
    void doc.getPage(number).then((page) => {
      const element = canvas.current
      if (cancelled || !element) return
      const base = page.getViewport({ scale: 1 })
      const dpr = Math.min(window.devicePixelRatio || 1, MAX_DPR)
      const viewport = page.getViewport({ scale: (width / base.width) * dpr })
      element.width = Math.round(viewport.width)
      element.height = Math.round(viewport.height)
      const task = page.render({ canvas: element, viewport })
      stop = () => task.cancel()
      // Cancelling a render rejects its promise; that is the normal path here.
      task.promise.catch(() => undefined)
    })
    return () => {
      cancelled = true
      stop?.()
    }
  }, [doc, number, width, near])

  return (
    <div
      ref={holder}
      data-page={number}
      className="relative mx-auto mb-3 bg-white shadow-sm ring-1 ring-black/5"
      style={{ width, height: Math.round(width * ratio) }}
    >
      <canvas ref={canvas} className="block h-full w-full" />
      {highlights.map((box, index) => (
        <span
          key={`${box.x0}-${box.y0}-${index}`}
          aria-hidden
          className="pointer-events-none absolute rounded-sm bg-accent/25 ring-1 ring-accent/70"
          style={{
            left: `${box.x0 * 100}%`,
            top: `${box.y0 * 100}%`,
            width: `${(box.x1 - box.x0) * 100}%`,
            height: `${(box.y1 - box.y0) * 100}%`,
          }}
        />
      ))}
    </div>
  )
}
