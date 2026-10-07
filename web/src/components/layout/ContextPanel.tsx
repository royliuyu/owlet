import { Maximize2, Minimize2, PanelRightClose, X } from 'lucide-react'
import { sourceRegistry } from '@/components/cards/registry'
import { useWorkspace } from '@/app/workspace'
import type { ReaderSpan } from '@/lib/layout'
import type { OpenDocument } from '@/lib/types'

export function ContextPanel({
  mode,
  width,
  span,
  onSpan,
  onClose,
}: {
  mode: 'column' | 'overlay' | 'sheet'
  width?: number
  span?: Extract<ReaderSpan, 'split' | 'max'>
  onSpan?: (span: ReaderSpan) => void
  onClose?: () => void
}) {
  const { selection } = useWorkspace()
  const frame =
    mode === 'column'
      ? 'flex h-full w-full min-h-0 flex-col bg-paper'
      : mode === 'overlay'
        ? 'absolute inset-y-0 right-0 z-10 flex flex-col border-l border-line bg-paper shadow-2xl'
        : 'relative z-10 flex h-[75dvh] max-h-[85dvh] w-full flex-col rounded-t-2xl border-t border-line bg-paper-raised pb-[env(safe-area-inset-bottom)] shadow-2xl'

  const panel = (
    <section className={frame} style={mode === 'sheet' ? undefined : { width }} aria-label="Reader">
      {mode === 'sheet' ? <div className="mx-auto mt-2 h-1 w-10 rounded-full bg-line" /> : null}
      {selection ? (
        <Reader
          selection={selection}
          span={span}
          onSpan={onSpan}
          onClose={mode === 'column' ? undefined : onClose}
        />
      ) : (
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="flex items-center justify-end border-b border-line px-3 py-2">
            <PanelActions span={span} onSpan={onSpan} onClose={mode === 'column' ? undefined : onClose} />
          </div>
          <div className="flex flex-1 items-center px-6">
            <p className="font-serif text-xl leading-snug text-muted">
              Choose a paper or a citation to read it here.
            </p>
          </div>
        </div>
      )}
    </section>
  )

  if (mode === 'overlay' && onClose) {
    return (
      <div className="fixed inset-0 z-30">
        <button type="button" className="absolute inset-0 bg-ink/20" aria-label="Close reader" onClick={onClose} />
        {panel}
      </div>
    )
  }
  if (mode === 'sheet' && onClose) {
    return (
      <div className="fixed inset-0 z-40 flex flex-col justify-end">
        <button type="button" className="absolute inset-0 bg-ink/30" aria-label="Close reader" onClick={onClose} />
        {panel}
      </div>
    )
  }
  return panel
}

function Reader({
  selection,
  span,
  onSpan,
  onClose,
}: {
  selection: OpenDocument
  span?: Extract<ReaderSpan, 'split' | 'max'>
  onSpan?: (span: ReaderSpan) => void
  onClose?: () => void
}) {
  const renderer = sourceRegistry[selection.kind]
  const Viewer = renderer.Viewer
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex items-start gap-3 border-b border-line px-4 py-3">
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-medium tracking-wide text-muted uppercase">{renderer.label}</p>
          <h2 className="truncate font-serif text-xl">{selection.title}</h2>
        </div>
        <PanelActions span={span} onSpan={onSpan} onClose={onClose} />
      </header>
      {Viewer ? (
        <Viewer
          docId={selection.docId}
          title={selection.title}
          page={selection.page}
          bboxes={selection.bboxes}
        />
      ) : (
        <p className="px-4 py-4 text-sm text-muted">
          {renderer.label} can be indexed, and a viewer for this format is not wired up yet.
        </p>
      )}
    </div>
  )
}

function PanelActions({
  span,
  onSpan,
  onClose,
}: {
  span?: Extract<ReaderSpan, 'split' | 'max'>
  onSpan?: (span: ReaderSpan) => void
  onClose?: () => void
}) {
  if (!onSpan && !onClose) return null
  return (
    <div className="flex shrink-0 items-center gap-0.5">
      {onSpan && span === 'max' ? (
        <button type="button" aria-label="Restore reader" className={actionClass} onClick={() => onSpan('split')}>
          <Minimize2 size={16} />
        </button>
      ) : null}
      {onSpan && span !== 'max' ? (
        <button type="button" aria-label="Maximize reader" className={actionClass} onClick={() => onSpan('max')}>
          <Maximize2 size={16} />
        </button>
      ) : null}
      {onSpan ? (
        <button type="button" aria-label="Hide reader" className={actionClass} onClick={() => onSpan('min')}>
          <PanelRightClose size={16} />
        </button>
      ) : null}
      {onClose ? (
        <button type="button" aria-label="Close reader" className={actionClass} onClick={onClose}>
          <X size={18} />
        </button>
      ) : null}
    </div>
  )
}

const actionClass = 'rounded-lg p-1.5 text-muted hover:bg-paper-raised hover:text-ink'
