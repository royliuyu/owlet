import { File } from 'lucide-react'
import type { CardProps } from '@/components/cards/registry'
import { SourceCard } from '@/components/cards/SourceCard'

export function FileCard(props: CardProps) {
  return <SourceCard icon={File} kicker="File" {...props} />
}
