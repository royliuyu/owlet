import type { Block, ChatStreamEvent, Citation } from '@/lib/types'

export function applyStreamEvent(blocks: Block[], event: ChatStreamEvent): Block[] {
  switch (event.event) {
    case 'delta':
      return appendText(blocks, event.text)
    case 'tool':
      return replaceTool(blocks, event)
    case 'citation':
      return appendCitation(blocks, event.citation)
    case 'action':
      return [
        ...blocks,
        {
          type: 'action',
          action_id: event.action_id,
          kind: event.kind,
          params: event.params,
        },
      ]
    case 'error':
      return [...blocks, { type: 'error', message: event.message }]
    default:
      return blocks
  }
}

function appendText(blocks: Block[], text: string): Block[] {
  const next = [...blocks]
  const last = next[next.length - 1]
  if (last?.type === 'text') {
    next[next.length - 1] = { type: 'text', content: last.content + text }
    return next
  }
  next.push({ type: 'text', content: text })
  return next
}

function appendCitation(blocks: Block[], citation: Citation): Block[] {
  const next = [...blocks]
  const index = next.findIndex((block) => block.type === 'citations')
  if (index === -1) {
    next.push({ type: 'citations', items: [citation] })
    return next
  }
  const current = next[index]
  if (current.type !== 'citations') return next
  next[index] = { type: 'citations', items: [...current.items, citation] }
  return next
}

function replaceTool(blocks: Block[], event: Extract<ChatStreamEvent, { event: 'tool' }>): Block[] {
  const update: Block = {
    type: 'tool',
    tool: event.tool,
    status: event.status,
    summary: toolSummary(event.tool, event.status, event.hits),
  }
  // "running" and "done" are one step, so the second event replaces the first
  // instead of leaving both lines in the transcript.
  const index = blocks.findIndex(
    (block) => block.type === 'tool' && block.tool === event.tool && block.status === 'running',
  )
  if (index === -1) return [...blocks, update]
  const next = [...blocks]
  next[index] = update
  return next
}

function toolSummary(tool: string, status: 'running' | 'done', hits?: number): string {
  const records = tool === 'list_records'
  if (status === 'running') return records ? 'Checking library records…' : 'Searching the library…'
  if (hits === 0) return 'Nothing matched in the library'
  if (typeof hits === 'number') {
    const noun = records
      ? hits === 1
        ? 'document'
        : 'documents'
      : hits === 1
        ? 'passage'
        : 'passages'
    return `Found ${hits} ${noun}`
  }
  return `${tool.replaceAll('_', ' ')} finished`
}
