/** A small markdown subset for chat answers. Text stays text; nothing becomes HTML. */

export type Inline =
  | { type: 'text'; text: string }
  | { type: 'strong'; children: Inline[] }
  | { type: 'em'; children: Inline[] }
  | { type: 'code'; text: string }
  | { type: 'cite'; n: number }

export type AnswerBlock =
  | { type: 'p'; inlines: Inline[] }
  | { type: 'h'; level: number; inlines: Inline[] }
  | { type: 'ul'; items: Inline[][] }
  | { type: 'ol'; items: Inline[][] }
  | { type: 'code'; text: string }

export function parseAnswer(content: string): AnswerBlock[] {
  const lines = content.replace(/\r\n/g, '\n').split('\n')
  const blocks: AnswerBlock[] = []
  let paragraph: string[] = []

  function flushParagraph() {
    const text = paragraph.join(' ').trim()
    paragraph = []
    if (text) blocks.push({ type: 'p', inlines: parseInline(text) })
  }

  let index = 0
  while (index < lines.length) {
    const line = lines[index]
    if (line.trim() === '') {
      flushParagraph()
      index += 1
      continue
    }

    if (line.trimStart().startsWith('```')) {
      flushParagraph()
      const body: string[] = []
      index += 1
      while (index < lines.length && !lines[index].trimStart().startsWith('```')) {
        body.push(lines[index])
        index += 1
      }
      if (index < lines.length) index += 1
      blocks.push({ type: 'code', text: body.join('\n') })
      continue
    }

    const heading = /^(#{1,3})\s+(.+)$/.exec(line.trim())
    if (heading) {
      flushParagraph()
      blocks.push({
        type: 'h',
        level: heading[1].length,
        inlines: parseInline(heading[2]),
      })
      index += 1
      continue
    }

    if (/^[-*]\s+/.test(line)) {
      flushParagraph()
      const items: string[] = []
      while (index < lines.length && /^[-*]\s+/.test(lines[index])) {
        let item = lines[index].replace(/^[-*]\s+/, '')
        index += 1
        while (index < lines.length && /^\s{2,}\S/.test(lines[index])) {
          item += ` ${lines[index].trim()}`
          index += 1
        }
        items.push(item)
      }
      blocks.push({ type: 'ul', items: items.map(parseInline) })
      continue
    }

    if (/^\d+[.)]\s+/.test(line)) {
      flushParagraph()
      const items: string[] = []
      while (index < lines.length && /^\d+[.)]\s+/.test(lines[index])) {
        let item = lines[index].replace(/^\d+[.)]\s+/, '')
        index += 1
        while (index < lines.length && /^\s{2,}\S/.test(lines[index])) {
          item += ` ${lines[index].trim()}`
          index += 1
        }
        items.push(item)
      }
      blocks.push({ type: 'ol', items: items.map(parseInline) })
      continue
    }

    paragraph.push(line.trim())
    index += 1
  }

  flushParagraph()
  return blocks
}

export function parseInline(text: string): Inline[] {
  const nodes: Inline[] = []
  let index = 0
  let plain = ''

  function flushPlain() {
    if (plain) nodes.push({ type: 'text', text: plain })
    plain = ''
  }

  while (index < text.length) {
    if (text.startsWith('**', index) || text.startsWith('__', index)) {
      const marker = text.slice(index, index + 2)
      const end = text.indexOf(marker, index + 2)
      if (end > index + 2) {
        flushPlain()
        nodes.push({ type: 'strong', children: parseInline(text.slice(index + 2, end)) })
        index = end + 2
        continue
      }
    }

    const emphasis = takeEmphasis(text, index)
    if (emphasis) {
      flushPlain()
      nodes.push({ type: 'em', children: parseInline(emphasis.inner) })
      index = emphasis.next
      continue
    }

    if (text[index] === '`') {
      const end = text.indexOf('`', index + 1)
      if (end > index + 1) {
        flushPlain()
        nodes.push({ type: 'code', text: text.slice(index + 1, end) })
        index = end + 1
        continue
      }
    }

    const cite = /^\[(\d+)\]/.exec(text.slice(index))
    if (cite) {
      flushPlain()
      nodes.push({ type: 'cite', n: Number(cite[1]) })
      index += cite[0].length
      continue
    }

    plain += text[index]
    index += 1
  }

  flushPlain()
  return nodes
}

function takeEmphasis(text: string, index: number): { inner: string; next: number } | null {
  const marker = text[index]
  if ((marker !== '*' && marker !== '_') || text[index + 1] === marker) return null
  if (index > 0 && isWord(text[index - 1])) return null
  const rest = text.slice(index + 1)
  const end = rest.indexOf(marker)
  if (end <= 0 || rest[end + 1] === marker || rest.slice(0, end).includes('\n')) return null
  const after = rest[end + 1]
  if (after !== undefined && isWord(after)) return null
  if (/\s/.test(rest[0]) || /\s/.test(rest[end - 1])) return null
  return { inner: rest.slice(0, end), next: index + end + 2 }
}

function isWord(char: string): boolean {
  return /[\p{L}\p{N}]/u.test(char)
}
