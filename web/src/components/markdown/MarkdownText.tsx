import { Fragment, type ReactNode } from 'react'
import { parseAnswer, type Inline } from '@/lib/answerMarkdown'
import { cn } from '@/lib/cn'

export function ViewSwitch({ raw, onChange }: { raw: boolean; onChange: (raw: boolean) => void }) {
  return (
    <div className="inline-flex self-start rounded-full border border-line p-0.5 text-xs">
      <button
        type="button"
        aria-pressed={!raw}
        onClick={() => onChange(false)}
        className={cn('rounded-full px-2.5 py-1', !raw ? 'bg-ink text-paper' : 'text-muted hover:text-ink')}
      >
        Rendered
      </button>
      <button
        type="button"
        aria-pressed={raw}
        onClick={() => onChange(true)}
        className={cn('rounded-full px-2.5 py-1', raw ? 'bg-ink text-paper' : 'text-muted hover:text-ink')}
      >
        Markdown
      </button>
    </div>
  )
}

export function MarkdownText({
  content,
  raw,
  renderCite,
  prose = 'font-serif text-[17px] leading-7',
}: {
  content: string
  raw: boolean
  renderCite?: (n: number) => ReactNode
  prose?: string
}) {
  if (raw) {
    return <p className={cn(prose, 'whitespace-pre-wrap')}>{content}</p>
  }
  const blocks = parseAnswer(content)
  return (
    <div className={cn('flex flex-col gap-3', prose)}>
      {blocks.map((block, index) => {
        if (block.type === 'h') {
          return (
            <p key={index} className={cn('font-semibold', block.level === 1 && 'text-xl')}>
              <Inlines nodes={block.inlines} renderCite={renderCite} />
            </p>
          )
        }
        if (block.type === 'ul' || block.type === 'ol') {
          const List = block.type === 'ul' ? 'ul' : 'ol'
          return (
            <List
              key={index}
              className={cn('flex flex-col gap-1.5 pl-5', block.type === 'ul' ? 'list-disc' : 'list-decimal')}
            >
              {block.items.map((item, itemIndex) => (
                <li key={itemIndex}>
                  <Inlines nodes={item} renderCite={renderCite} />
                </li>
              ))}
            </List>
          )
        }
        if (block.type === 'code') {
          return (
            <pre
              key={index}
              className="overflow-auto rounded-xl bg-paper-raised px-3 py-2 font-sans text-sm leading-6 whitespace-pre-wrap"
            >
              {block.text}
            </pre>
          )
        }
        return (
          <p key={index}>
            <Inlines nodes={block.inlines} renderCite={renderCite} />
          </p>
        )
      })}
    </div>
  )
}

function Inlines({
  nodes,
  renderCite,
}: {
  nodes: Inline[]
  renderCite?: (n: number) => ReactNode
}) {
  return nodes.map((node, index) => {
    if (node.type === 'text') return <span key={index}>{node.text}</span>
    if (node.type === 'strong') {
      return (
        <strong key={index} className="font-semibold">
          <Inlines nodes={node.children} renderCite={renderCite} />
        </strong>
      )
    }
    if (node.type === 'em') {
      return (
        <em key={index}>
          <Inlines nodes={node.children} renderCite={renderCite} />
        </em>
      )
    }
    if (node.type === 'code') {
      return (
        <code key={index} className="rounded bg-paper-raised px-1 font-sans text-[0.9em]">
          {node.text}
        </code>
      )
    }
    if (renderCite) return <Fragment key={index}>{renderCite(node.n)}</Fragment>
    return <span key={index}>[{node.n}]</span>
  })
}
