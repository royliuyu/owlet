import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useWorkspace } from '@/app/workspace'
import { Composer } from '@/components/chat/Composer'
import { MessageList } from '@/components/chat/MessageList'
import { beginConversation, useConversations } from '@/lib/conversations'
import { focusDocId, priorQuestion } from '@/lib/focus'
import { useChatStream } from '@/lib/useChatStream'

export function ChatView() {
  const { id } = useParams()
  const navigate = useNavigate()
  const conversations = useConversations()
  const conversation = conversations.find((item) => item.id === id)
  const { sources, openDocument } = useWorkspace()
  const { streaming, send, stop } = useChatStream()
  const [draft, setDraft] = useState('')
  const scroller = useRef<HTMLDivElement>(null)
  const messages = conversation?.messages ?? []

  useEffect(() => {
    const node = scroller.current
    if (node) node.scrollTop = node.scrollHeight
  }, [conversation?.updatedAt])

  async function submit() {
    const text = draft.trim()
    if (!text || streaming) return
    const conversationId = id ?? crypto.randomUUID()
    if (!id || !conversation) {
      beginConversation(conversationId)
      if (!id) navigate(`/chat/${conversationId}`)
    }
    setDraft('')
    await send({
      conversationId,
      question: text,
      sources,
      focusDocId: focusDocId(messages),
      priorQuestion: priorQuestion(messages),
    })
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div ref={scroller} className="min-h-0 flex-1 overflow-auto">
        {messages.length === 0 ? (
          <div className="mx-auto flex h-full max-w-xl flex-col justify-center px-6">
            <p className="font-serif text-3xl leading-tight">Ask from the papers on this machine.</p>
            <p className="mt-3 text-muted">
              Answers will cite a page you can open beside the chat. Add a folder in Settings if the
              library is empty.
            </p>
          </div>
        ) : (
          <MessageList messages={messages} streaming={streaming} onOpen={openDocument} />
        )}
      </div>
      <Composer
        value={draft}
        streaming={streaming}
        onChange={setDraft}
        onSubmit={() => void submit()}
        onStop={stop}
      />
    </div>
  )
}
