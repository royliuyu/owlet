import { CircleDashed } from 'lucide-react'
import type { CardProps } from '@/components/cards/registry'
import { SourceCard } from '@/components/cards/SourceCard'

export function PlaceholderCard(props: CardProps) {
  return <SourceCard icon={CircleDashed} kicker="Source" {...props} />
}
