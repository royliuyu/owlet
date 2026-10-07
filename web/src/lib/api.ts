import type {
  ChatRequest,
  ChatStreamEvent,
  Citation,
  Collection,
  DocumentPreview,
  GoogleAttempt,
  GoogleEvent,
  GoogleOverview,
  GoogleSignIn,
  IndexStatus,
  LibraryFile,
  SourceKind,
} from '@/lib/types'

const TOKEN_KEY = 'owlet.token'

/** Settings tells the sidebar that a calendar was checked or an account left. */
export const ACCOUNTS_CHANGED = 'owlet-accounts-changed'

export function notifyAccountsChanged(): void {
  window.dispatchEvent(new Event(ACCOUNTS_CHANGED))
}

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export function readToken(): string {
  return localStorage.getItem(TOKEN_KEY) ?? ''
}

export function writeToken(token: string): void {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

export function documentUrl(docId: string, view: 'meta' | 'file'): string {
  const path = docId.split('/').map(encodeURIComponent).join('/')
  return `/api/v1/documents/${path}?view=${view}`
}

export async function openSession(token: string): Promise<void> {
  await request('/api/v1/session', {
    method: 'POST',
    body: JSON.stringify({ token }),
  })
}

export function listCollections(): Promise<Collection[]> {
  return request<Collection[]>('/api/v1/collections')
}

export function addCollection(body: { path: string; label?: string }): Promise<Collection> {
  return request<Collection>('/api/v1/collections', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function updateCollection(
  id: string,
  body: { label?: string; enabled?: boolean },
): Promise<Collection> {
  return request<Collection>(`/api/v1/collections/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export function removeCollection(id: string): Promise<void> {
  return request(`/api/v1/collections/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

export function getGoogle(): Promise<GoogleOverview> {
  return request<GoogleOverview>('/api/v1/google/accounts')
}

export function saveGoogleClient(body: {
  client_id: string
  client_secret?: string
  account_email?: string
}): Promise<GoogleOverview> {
  return request<GoogleOverview>('/api/v1/google/client', {
    method: 'PUT',
    body: JSON.stringify(body),
  })
}

export function startGoogleSignIn(body: {
  product: 'calendar' | 'mail'
  account_id?: string
}): Promise<GoogleSignIn> {
  return request<GoogleSignIn>('/api/v1/google/connect', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function getGoogleAttempt(attemptId: string): Promise<GoogleAttempt> {
  return request<GoogleAttempt>(`/api/v1/google/attempts/${encodeURIComponent(attemptId)}`)
}

export function cancelGoogleAttempt(attemptId: string): Promise<GoogleAttempt> {
  return request<GoogleAttempt>(
    `/api/v1/google/attempts/${encodeURIComponent(attemptId)}/cancel`,
    { method: 'POST' },
  )
}

export function getGoogleEvents(): Promise<GoogleEvent[]> {
  return request<GoogleEvent[]>('/api/v1/google/events')
}

export function syncGoogleAccount(accountId: string): Promise<GoogleOverview['accounts'][number]> {
  return request(`/api/v1/google/accounts/${encodeURIComponent(accountId)}/sync`, {
    method: 'POST',
  })
}

export function disconnectGoogleAccount(accountId: string): Promise<void> {
  return request(`/api/v1/google/accounts/${encodeURIComponent(accountId)}`, {
    method: 'DELETE',
  })
}

export function setGoogleCalendar(
  accountId: string,
  body: { calendar_id: string; enabled: boolean },
): Promise<GoogleOverview['accounts'][number]> {
  return request(`/api/v1/google/accounts/${encodeURIComponent(accountId)}/calendars`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export function listFiles(collectionId: string): Promise<LibraryFile[]> {
  return request<LibraryFile[]>(`/api/v1/collections/${encodeURIComponent(collectionId)}/files`)
}

export function getDocument(docId: string): Promise<DocumentPreview> {
  return request<DocumentPreview>(documentUrl(docId, 'meta'))
}

export function startIndex(force = false): Promise<IndexStatus> {
  return request<IndexStatus>('/api/v1/index', {
    method: 'POST',
    body: JSON.stringify({ force }),
  })
}

export function getIndexStatus(): Promise<IndexStatus> {
  return request<IndexStatus>('/api/v1/index/status')
}

export function confirmAction(actionId: string): Promise<void> {
  return request(`/api/v1/actions/${encodeURIComponent(actionId)}/confirm`, { method: 'POST' })
}

export async function streamChat(
  body: ChatRequest,
  onEvent: (event: ChatStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch('/api/v1/chat', {
    method: 'POST',
    credentials: 'include',
    headers: { ...headers(), 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  if (!response.ok || !response.body) {
    throw new ApiError(response.status, await errorMessage(response))
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const frames = buffer.split('\n\n')
    buffer = frames.pop() ?? ''
    for (const frame of frames) {
      const event = parseFrame(frame)
      if (event) onEvent(event)
    }
  }
}

function headers(): Record<string, string> {
  const token = readToken()
  const result: Record<string, string> = { Accept: 'application/json' }
  if (token) result.Authorization = `Bearer ${token}`
  return result
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: 'include',
    headers: { ...headers(), 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!response.ok) throw new ApiError(response.status, await errorMessage(response))
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json()
    if (body && typeof body === 'object') {
      if ('message' in body && typeof body.message === 'string') return body.message
      if ('detail' in body && typeof body.detail === 'string') return body.detail
    }
  } catch {
    /* response was not JSON */
  }
  return `Request failed (${response.status})`
}

function parseFrame(frame: string): ChatStreamEvent | null {
  let name = 'message'
  const dataLines: string[] = []
  for (const line of frame.split('\n')) {
    if (!line || line.startsWith(':')) continue
    if (line.startsWith('event:')) name = line.slice(6).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
  }
  if (!dataLines.length) return null
  let data: Record<string, unknown>
  try {
    data = JSON.parse(dataLines.join('\n')) as Record<string, unknown>
  } catch {
    return null
  }
  return toEvent(name, data)
}

function toEvent(name: string, data: Record<string, unknown>): ChatStreamEvent | null {
  switch (name) {
    case 'start':
      return { event: 'start', message_id: String(data.message_id ?? '') }
    case 'delta':
      return { event: 'delta', text: String(data.text ?? '') }
    case 'tool':
      return {
        event: 'tool',
        tool: String(data.tool ?? ''),
        status: data.status === 'running' ? 'running' : 'done',
        hits: typeof data.hits === 'number' ? data.hits : undefined,
      }
    case 'citation':
      return { event: 'citation', citation: citationFrom(data) }
    case 'action':
      return {
        event: 'action',
        action_id: String(data.action_id ?? ''),
        kind: String(data.kind ?? ''),
        params: isRecord(data.params) ? data.params : {},
      }
    case 'error':
      return { event: 'error', message: String(data.message ?? 'Something went wrong') }
    case 'done':
      return { event: 'done', latency_ms: Number(data.latency_ms ?? 0) }
    default:
      return null
  }
}

function citationFrom(data: Record<string, unknown>): Citation {
  return {
    n: Number(data.n ?? 0),
    kind: (data.kind as SourceKind) ?? 'file',
    doc_id: String(data.doc_id ?? ''),
    title: String(data.title ?? ''),
    uri: String(data.uri ?? ''),
    locator: isRecord(data.locator) ? data.locator : {},
    snippet: String(data.snippet ?? ''),
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
