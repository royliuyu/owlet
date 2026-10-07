import { BlockRenderer } from '@/components/blocks/BlockRenderer'
import type { ChatMessage, OpenDocument } from '@/lib/types'

export function MessageList({
  messages,
  streaming,
  onOpen,
}: {
  messages: ChatMessage[]
  streaming: boolean
  onOpen: (document: OpenDocument) => void
}) {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-6">
      {messages.map((message, index) =>
        message.role === 'user' ? (
          <p
            key={message.id}
            className="ml-auto max-w-[36rem] rounded-2xl bg-ink px-4 py-3 whitespace-pre-wrap text-paper"
          >
            {message.blocks[0]?.type === 'text' ? message.blocks[0].content : ''}
          </p>
        ) : (
          <div key={message.id}>
            {message.blocks.length === 0 && streaming && index === messages.length - 1 ? (
              <p className="text-sm text-muted">Working…</p>
            ) : (
              <BlockRenderer blocks={message.blocks} onOpen={onOpen} />
            )}
          </div>
        ),
      )}
    </div>
  )
}
