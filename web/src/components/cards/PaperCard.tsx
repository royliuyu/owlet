import { FileText } from 'lucide-react'
import type { CardProps } from '@/components/cards/registry'
import { SourceCard } from '@/components/cards/SourceCard'

export function PaperCard(props: CardProps) {
  return <SourceCard icon={FileText} kicker="Paper" {...props} />
}
