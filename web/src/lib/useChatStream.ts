import { useEffect, useRef, useState } from 'react'
import { ApiError, streamChat } from '@/lib/api'
import { appendUserMessage, setAssistantBlocks, startAssistant } from '@/lib/conversations'
import { applyStreamEvent } from '@/lib/stream'
import type { Block, SourceKind } from '@/lib/types'

export function useChatStream() {
  const [streaming, setStreaming] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => () => abortRef.current?.abort(), [])

  async function send(input: {
    conversationId: string
    question: string
    sources: SourceKind[]
    focusDocId?: string
    priorQuestion?: string
  }) {
    if (streaming) return
    appendUserMessage(input.conversationId, input.question)
    const assistantId = crypto.randomUUID()
    startAssistant(input.conversationId, assistantId)
    setStreaming(true)
    const controller = new AbortController()
    abortRef.current = controller
    let blocks: Block[] = []
    try {
      await streamChat(
        {
          conversation_id: input.conversationId,
          question: input.question,
          sources: input.sources,
          focus_doc_id: input.focusDocId,
          prior_question: input.priorQuestion,
        },
        (event) => {
          blocks = applyStreamEvent(blocks, event)
          setAssistantBlocks(input.conversationId, assistantId, blocks)
        },
        controller.signal,
      )
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === 'AbortError') return
      const message = reason instanceof ApiError ? reason.message : 'The request failed'
      setAssistantBlocks(input.conversationId, assistantId, [
        ...blocks,
        { type: 'error', message },
      ])
    } finally {
      setStreaming(false)
    }
  }

  return {
    streaming,
    send,
    stop: () => abortRef.current?.abort(),
  }
}
