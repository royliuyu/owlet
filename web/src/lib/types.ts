/**
 * Contract mirrored from src/core/domain/models.py and domain/chat.py.
 * Change both sides together.
 */

export type SourceKind = 'paper' | 'note' | 'email' | 'event' | 'file' | 'task'

export type Document = {
  id: string
  source: SourceKind
  source_id: string
  title: string
  uri: string
  author: string | null
  participants: string[]
  collection: string | null
  created_at: string
  updated_at: string
  content_hash: string
  extra: Record<string, unknown>
}

/** Fractions of the page box, top-left origin, so any zoom works. */
export type BBox = {
  page: number
  x0: number
  y0: number
  x1: number
  y1: number
}

export type Citation = {
  n: number
  kind: SourceKind
  doc_id: string
  title: string
  uri: string
  locator: Record<string, unknown>
  snippet: string
}

export type IndexStatus = {
  running: boolean
  status?: string
  documents: number
  chunks: number
  embedded: number
  documents_seen?: number
  documents_indexed?: number
  documents_skipped?: number
  chunks_written?: number
  chunks_embedded?: number
  failures?: string[]
  detail?: string
}

export type Block =
  | { type: 'text'; content: string }
  | { type: 'tool'; tool: string; status: 'running' | 'done'; summary: string }
  | { type: 'citations'; items: Citation[] }
  | { type: 'action'; action_id: string; kind: string; params: Record<string, unknown> }
  | { type: 'error'; message: string }

export type ChatRequest = {
  conversation_id?: string
  question: string
  sources?: SourceKind[] | null
  filters?: Record<string, unknown>
  /** The paper the previous turn cited. Omitted on the first question. */
  focus_doc_id?: string
  /** The user message before this one, so a follow-up keeps its subject. */
  prior_question?: string
}

export type ChatStreamEvent =
  | { event: 'start'; message_id: string }
  | { event: 'delta'; text: string }
  | { event: 'tool'; tool: string; status: 'running' | 'done'; hits?: number }
  | { event: 'citation'; citation: Citation }
  | { event: 'action'; action_id: string; kind: string; params: Record<string, unknown> }
  | { event: 'error'; message: string }
  | { event: 'done'; latency_ms: number }

export type ChatMessage = {
  id: string
  role: 'user' | 'assistant'
  blocks: Block[]
}

export type Conversation = {
  id: string
  title: string
  messages: ChatMessage[]
  updatedAt: string
}

export type Collection = {
  id: string
  label: string
  path: string
  enabled: boolean
}

export type GoogleCalendar = {
  calendar_id: string
  summary: string
  primary: boolean
  enabled: boolean
  held_by: string | null
}

export type GoogleAccount = {
  id: string
  email: string
  status: 'connected' | 'reconnect'
  scopes: string[]
  last_sync_at: string | null
  calendars: GoogleCalendar[]
  event_count: number
}

export type GoogleOverview = {
  configured: boolean
  client_id: string
  account_email: string
  redirect_uris: string[]
  accounts: GoogleAccount[]
}

export type GoogleSignIn = {
  attempt_id: string
  url: string
  opened_on_server: boolean
  opened_locally: boolean
}

export type GoogleEvent = {
  id: string
  summary: string
  start: string
  end: string
  all_day: boolean
  location: string
  description: string
  recurrence: string
  calendar: string
}

export type GoogleAttempt = {
  status: 'pending' | 'connected' | 'cancelled' | 'denied' | 'expired' | 'mismatch' | 'error'
  email: string | null
  message: string
}

export type LibraryFile = {
  id: string
  source: SourceKind
  source_id: string
  title: string
  uri: string
  collection: string | null
  media_type: string
  updated_at: string
  content_hash: string
}

export type PagePreview = {
  page: number
  text: string
}

/** Word reading order. Other formats leave this empty and use `pages`. */
export type PreviewBlock = {
  kind: 'heading' | 'paragraph' | 'list' | 'table'
  text: string
  level: number
  ordered: boolean
  items: string[]
  rows: string[][]
}

export type DocumentPreview = {
  document: Document
  pages: PagePreview[]
  blocks: PreviewBlock[]
}

export type OpenDocument = {
  docId: string
  title: string
  kind: SourceKind
  page?: number
  snippet?: string
  bboxes?: BBox[]
}
