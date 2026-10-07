import type { LucideIcon } from 'lucide-react'
import type { CardProps } from '@/components/cards/registry'
import { cn } from '@/lib/cn'

export function SourceCard({
  icon: Icon,
  kicker,
  title,
  detail,
  meta,
  suffix,
  selected,
  onOpen,
}: CardProps & { icon: LucideIcon; kicker: string }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className={cn(
        'flex w-full gap-3 rounded-xl border px-3 py-3 text-left transition-colors',
        selected
          ? 'border-accent bg-accent-soft'
          : 'border-line bg-paper-raised hover:border-ink/25',
      )}
    >
      <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-paper text-accent">
        <Icon size={16} aria-hidden />
      </span>
      <span className="min-w-0">
        <span className="flex items-baseline gap-2 text-[11px] font-medium tracking-wide text-muted">
          <span className="uppercase">{kicker}</span>
          {suffix ? <span className="font-normal tracking-normal">{suffix}</span> : null}
        </span>
        <span className="mt-0.5 block truncate font-medium text-ink">{title}</span>
        {detail ? <span className="mt-1 block line-clamp-2 text-sm text-muted">{detail}</span> : null}
        {meta ? <span className="mt-1 block text-xs text-muted">{meta}</span> : null}
      </span>
    </button>
  )
}
