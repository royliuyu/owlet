import { useSyncExternalStore } from 'react'
import type { Block, ChatMessage, Conversation } from '@/lib/types'

const KEY = 'owlet.conversations'

let state: Conversation[] = load()
const listeners = new Set<() => void>()

function load(): Conversation[] {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    return Array.isArray(parsed) ? (parsed as Conversation[]) : []
  } catch {
    return []
  }
}

function commit(next: Conversation[]) {
  state = next
  localStorage.setItem(KEY, JSON.stringify(state))
  listeners.forEach((listener) => listener())
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function useConversations(): Conversation[] {
  return useSyncExternalStore(subscribe, () => state, () => state)
}

export function beginConversation(id: string): void {
  if (state.some((item) => item.id === id)) return
  commit([
    { id, title: 'New chat', messages: [], updatedAt: new Date().toISOString() },
    ...state,
  ])
}

export function appendUserMessage(conversationId: string, text: string): void {
  const message: ChatMessage = {
    id: crypto.randomUUID(),
    role: 'user',
    blocks: [{ type: 'text', content: text }],
  }
  change(conversationId, (conversation) => ({
    ...conversation,
    title: conversation.title === 'New chat' ? clip(text) : conversation.title,
    messages: [...conversation.messages, message],
  }))
}

export function startAssistant(conversationId: string, messageId: string): void {
  const message: ChatMessage = { id: messageId, role: 'assistant', blocks: [] }
  change(conversationId, (conversation) => ({
    ...conversation,
    messages: [...conversation.messages, message],
  }))
}

export function setAssistantBlocks(
  conversationId: string,
  messageId: string,
  blocks: Block[],
): void {
  change(conversationId, (conversation) => ({
    ...conversation,
    messages: conversation.messages.map((message) =>
      message.id === messageId ? { ...message, blocks } : message,
    ),
  }))
}

export function removeConversation(id: string): void {
  commit(state.filter((item) => item.id !== id))
}

function change(id: string, recipe: (conversation: Conversation) => Conversation) {
  const current = state.find((item) => item.id === id)
  if (!current) return
  const updated = { ...recipe(current), updatedAt: new Date().toISOString() }
  commit([updated, ...state.filter((item) => item.id !== id)])
}

function clip(text: string): string {
  const clean = text.replace(/\s+/g, ' ').trim()
  return clean.length > 48 ? `${clean.slice(0, 48)}…` : clean
}
