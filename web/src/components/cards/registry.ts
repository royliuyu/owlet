import {
  Calendar,
  CheckSquare,
  File,
  FileText,
  Library,
  ListChecks,
  Mail,
  MessageCircle,
  NotebookPen,
  Settings,
  SunMedium,
  type LucideIcon,
} from 'lucide-react'
import type { ComponentType } from 'react'
import { FileCard } from '@/components/cards/FileCard'
import { NoteCard } from '@/components/cards/NoteCard'
import { PaperCard } from '@/components/cards/PaperCard'
import { PlaceholderCard } from '@/components/cards/PlaceholderCard'
import { DocxViewer } from '@/components/viewers/DocxViewer'
import { MarkdownViewer } from '@/components/viewers/MarkdownViewer'
import { PdfViewer } from '@/components/viewers/PdfViewer'
import type { BBox, SourceKind } from '@/lib/types'

export type CardProps = {
  title: string
  detail?: string
  meta?: string
  /** Filename suffix, such as `.pdf` or `.md`. */
  suffix?: string
  selected?: boolean
  onOpen: () => void
}

export type ViewerProps = {
  docId: string
  title: string
  page?: number
  /** Where the cited passage sits, so the viewer can draw it. */
  bboxes?: BBox[]
}

export type SourceRenderer = {
  kind: SourceKind
  label: string
  description: string
  icon: LucideIcon
  connected: boolean
  Card: ComponentType<CardProps>
  Viewer: ComponentType<ViewerProps> | null
}

export const sourceRegistry: Record<SourceKind, SourceRenderer> = {
  paper: {
    kind: 'paper',
    label: 'Papers',
    description: 'PDFs from a configured folder',
    icon: FileText,
    connected: true,
    Card: PaperCard,
    Viewer: PdfViewer,
  },
  note: {
    kind: 'note',
    label: 'Notes',
    description: 'Markdown and plain text',
    icon: NotebookPen,
    connected: true,
    Card: NoteCard,
    Viewer: MarkdownViewer,
  },
  file: {
    kind: 'file',
    label: 'Files',
    description: 'Word (.docx)',
    icon: File,
    connected: true,
    Card: FileCard,
    Viewer: DocxViewer,
  },
  email: {
    kind: 'email',
    label: 'Mail',
    description: 'Not connected',
    icon: Mail,
    connected: false,
    Card: PlaceholderCard,
    Viewer: null,
  },
  event: {
    kind: 'event',
    label: 'Calendar',
    description: 'Google calendars checked in Settings',
    icon: Calendar,
    connected: true,
    Card: PlaceholderCard,
    Viewer: null,
  },
  task: {
    kind: 'task',
    label: 'Tasks',
    description: 'Not connected',
    icon: CheckSquare,
    connected: false,
    Card: PlaceholderCard,
    Viewer: null,
  },
}

export const sourceOrder: SourceKind[] = ['paper', 'note', 'file', 'email', 'event', 'task']

export const connectedSources: SourceKind[] = sourceOrder.filter(
  (kind) => sourceRegistry[kind].connected,
)

export const NAV: { to: string; label: string; icon: LucideIcon; match: string }[] = [
  { to: '/today', label: 'Today', icon: SunMedium, match: 'today' },
  { to: '/chat', label: 'Chat', icon: MessageCircle, match: 'chat' },
  { to: '/library', label: 'Library', icon: Library, match: 'library' },
  { to: '/actions', label: 'Actions', icon: ListChecks, match: 'actions' },
  { to: '/settings', label: 'Settings', icon: Settings, match: 'settings' },
]
