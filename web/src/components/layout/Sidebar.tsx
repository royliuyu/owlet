import { Plus, Trash2 } from 'lucide-react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { SourceFilterChips } from '@/components/chat/SourceFilterChips'
import { removeConversation, useConversations } from '@/lib/conversations'
import { cn } from '@/lib/cn'
import { useWorkspace } from '@/app/workspace'

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const conversations = useConversations()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const { sources, toggleSource } = useWorkspace()

  return (
    <div className="flex h-full min-h-0 flex-col bg-paper-raised">
      <div className="flex items-center justify-between px-3 py-3">
        <p className="font-serif text-xl tracking-tight">owlet</p>
        <button
          type="button"
          className="inline-flex items-center gap-1 rounded-full border border-line px-2.5 py-1 text-sm hover:border-ink/30"
          onClick={() => {
            navigate('/chat')
            onNavigate?.()
          }}
        >
          <Plus size={14} aria-hidden />
          New
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto px-2 pb-3">
        {conversations.length === 0 ? (
          <p className="px-2 py-3 text-sm text-muted">No conversations yet.</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {conversations.map((conversation) => (
              <li key={conversation.id} className="group flex items-center">
                <NavLink
                  to={`/chat/${conversation.id}`}
                  onClick={onNavigate}
                  className={({ isActive }) =>
                    cn(
                      'min-w-0 flex-1 truncate rounded-lg px-2 py-2 text-sm',
                      isActive ? 'bg-paper text-ink' : 'text-muted hover:bg-paper hover:text-ink',
                    )
                  }
                >
                  {conversation.title}
                </NavLink>
                <button
                  type="button"
                  aria-label={`Delete ${conversation.title}`}
                  className="mr-1 rounded p-1 text-muted opacity-70 hover:text-danger sm:opacity-0 sm:group-hover:opacity-100"
                  onClick={() => {
                    removeConversation(conversation.id)
                    if (pathname === `/chat/${conversation.id}`) navigate('/chat')
                  }}
                >
                  <Trash2 size={14} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="border-t border-line p-3">
        <SourceFilterChips selected={sources} onToggle={toggleSource} />
      </div>
    </div>
  )
}
