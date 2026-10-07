import { useRef } from 'react'

export function ResizeHandle({
  label,
  onDelta,
}: {
  label: string
  onDelta: (dx: number) => void
}) {
  const last = useRef(0)
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      className="group relative w-1.5 shrink-0 cursor-col-resize touch-none"
      onPointerDown={(event) => {
        event.currentTarget.setPointerCapture(event.pointerId)
        last.current = event.clientX
      }}
      onPointerMove={(event) => {
        if (!event.currentTarget.hasPointerCapture(event.pointerId)) return
        const dx = event.clientX - last.current
        last.current = event.clientX
        onDelta(dx)
      }}
    >
      <span className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-line group-hover:bg-accent" />
    </div>
  )
}
