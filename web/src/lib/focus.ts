import type { ChatMessage, Citation } from '@/lib/types'

/**
 * Words that show up in follow-ups and never identify a paper.
 * "paper" is longer than "HADD", so counting it would point at the wrong file.
 */
const GENERIC = new Set([
  'what',
  'whats',
  'this',
  'that',
  'paper',
  'papers',
  'abstract',
  'author',
  'authors',
  'first',
  'second',
  'third',
  'fourth',
  'fifth',
  'sixth',
  'seventh',
  'eighth',
  'last',
  'from',
  'with',
  'about',
  'does',
  'have',
  'been',
  'were',
  'they',
  'their',
  'into',
  'over',
  'under',
  'after',
  'before',
  'using',
  'based',
  'between',
  'other',
  'which',
  'when',
  'where',
  'whose',
  'your',
  'more',
  'most',
  'some',
  'many',
  'each',
  'both',
  'only',
  'also',
  'than',
  'then',
  'such',
  'same',
  'work',
  'works',
  'wrote',
  'written',
  'published',
  'title',
  'year',
])

/**
 * The paper a follow-up means by "this paper".
 *
 * A question that names a cited title sets the focus. A later question that
 * does not name one keeps it. The most-cited file in a wide search must not
 * replace the paper the conversation already named.
 */
export function priorQuestion(messages: ChatMessage[]): string | undefined {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index]
    if (message.role !== 'user') continue
    const text = message.blocks.find((item) => item.type === 'text')
    if (text && text.type === 'text' && text.content.trim()) return text.content
  }
  return undefined
}

export function focusDocId(messages: ChatMessage[]): string | undefined {
  let focus: string | undefined
  for (let index = 0; index < messages.length; index += 1) {
    const message = messages[index]
    if (message.role !== 'assistant') continue
    const block = message.blocks.find((item) => item.type === 'citations')
    if (!block || block.type !== 'citations' || block.items.length === 0) continue
    const named = namedIn(block.items, questionBefore(messages, index))
    if (named) focus = named
    else if (focus === undefined) focus = mostCited(block.items)
  }
  return focus
}

function questionBefore(messages: ChatMessage[], index: number): string {
  for (let earlier = index - 1; earlier >= 0; earlier -= 1) {
    const message = messages[earlier]
    if (message.role !== 'user') continue
    const text = message.blocks.find((item) => item.type === 'text')
    return text && text.type === 'text' ? text.content : ''
  }
  return ''
}

function namedIn(items: Citation[], asked: string): string | undefined {
  const tokens = asked
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter((token) => token.length >= 4 && !GENERIC.has(token))
  let bestId = ''
  let bestScore = 0
  for (const [docId, title] of titles(items)) {
    const hay = title.toLowerCase()
    const score = tokens.reduce((sum, token) => sum + (hay.includes(token) ? token.length : 0), 0)
    if (score > bestScore) {
      bestScore = score
      bestId = docId
    }
  }
  return bestId || undefined
}

function mostCited(items: Citation[]): string {
  const counts = new Map<string, number>()
  for (const item of items) counts.set(item.doc_id, (counts.get(item.doc_id) ?? 0) + 1)
  let mode = items[0].doc_id
  let modeCount = 0
  for (const [docId, count] of counts) {
    if (count > modeCount) {
      mode = docId
      modeCount = count
    }
  }
  return mode
}

function titles(items: Citation[]): Map<string, string> {
  const found = new Map<string, string>()
  for (const item of items) {
    if (!found.has(item.doc_id)) found.set(item.doc_id, item.title)
  }
  return found
}
