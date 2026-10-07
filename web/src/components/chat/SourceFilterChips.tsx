import { sourceOrder, sourceRegistry } from '@/components/cards/registry'
import { cn } from '@/lib/cn'
import type { SourceKind } from '@/lib/types'

export function SourceFilterChips({
  selected,
  ready,
  onToggle,
}: {
  selected: SourceKind[]
  /** Live overrides. Calendar becomes available once a calendar is checked. */
  ready?: Partial<Record<SourceKind, boolean>>
  onToggle: (kind: SourceKind) => void
}) {
  return (
    <fieldset className="min-w-0 border-0 p-0">
      <legend className="px-1 text-[11px] font-medium tracking-wide text-muted uppercase">
        Sources
      </legend>
      <div className="mt-2 flex flex-col gap-1">
        {sourceOrder.map((kind) => {
          const source = sourceRegistry[kind]
          const Icon = source.icon
          const available = ready?.[kind] ?? source.connected
          const checked = selected.includes(kind)
          return (
            <label
              key={kind}
              className={cn(
                'flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm',
                available ? 'cursor-pointer hover:bg-paper' : 'cursor-not-allowed opacity-50',
              )}
            >
              <input
                type="checkbox"
                className="accent-accent"
                checked={available && checked}
                disabled={!available}
                onChange={() => onToggle(kind)}
              />
              <Icon size={15} aria-hidden />
              <span className="flex-1">{source.label}</span>
              {available ? null : <span className="text-[11px] text-muted">Soon</span>}
            </label>
          )
        })}
      </div>
    </fieldset>
  )
}
