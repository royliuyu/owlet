import { NotebookPen } from 'lucide-react'
import type { CardProps } from '@/components/cards/registry'
import { SourceCard } from '@/components/cards/SourceCard'

export function NoteCard(props: CardProps) {
  return <SourceCard icon={NotebookPen} kicker="Note" {...props} />
}
