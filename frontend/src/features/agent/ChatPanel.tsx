import { useState } from 'react'
import { ChevronDown, ChevronRight, Send } from 'lucide-react'
import { Button } from '../../components/Button'
import { SkeletonRows } from '../../components/Skeleton'
import { Spinner } from '../../components/Spinner'
import { useChatMessages, useConversations, useSendChat } from './api'
import { READ_ONLY_REASON } from './labels'

const NEW_CHAT = 'new'

export function ChatPanel({ projectId, canChat }: { projectId: string; canChat: boolean }) {
  const [open, setOpen] = useState(true)
  const [picked, setPicked] = useState<string | null>(null) // null = latest, NEW_CHAT = a fresh conversation
  const [text, setText] = useState('')
  const [error, setError] = useState<string | null>(null)
  const conversations = useConversations(projectId)
  const send = useSendChat(projectId)

  const list = conversations.data ?? []
  const conversationId = picked === NEW_CHAT ? undefined : (picked ?? list[0]?.id)
  const messages = useChatMessages(conversationId)
  const msgs = messages.data ?? []
  const last = msgs[msgs.length - 1]
  const pending = last?.role === 'user'

  const onSend = () => {
    const message = text.trim()
    if (!message) return
    setError(null)
    send.mutate(
      { message, conversation_id: conversationId },
      {
        onSuccess: (r) => {
          setText('')
          setPicked(r.conversation_id)
        },
        onError: (e) => setError(e.message),
      },
    )
  }

  const Icon = open ? ChevronDown : ChevronRight
  return (
    <section aria-labelledby="agent-chat-h" className="rounded-card bg-white p-5">
      <h2 id="agent-chat-h" className="text-section font-semibold text-ink-title">
        <button
          type="button"
          aria-expanded={open}
          aria-controls="agent-chat-body"
          onClick={() => setOpen((o) => !o)}
          className="flex items-center gap-2 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
        >
          <Icon className="h-5 w-5" aria-hidden="true" />
          Chat with the agent
        </button>
      </h2>
      {open && (
        <div id="agent-chat-body" className="mt-3">
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-2 text-sm text-muted">
              Conversation
              <select
                value={picked === NEW_CHAT ? '' : (conversationId ?? '')}
                onChange={(e) => setPicked(e.target.value || null)}
                disabled={list.length === 0}
                className="max-w-48 rounded border border-hairline bg-white px-2 py-1 text-sm text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
              >
                {picked === NEW_CHAT && <option value="">New chat</option>}
                {list.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.title || new Date(c.created_at).toLocaleString()}
                  </option>
                ))}
              </select>
            </label>
            {canChat && (
              <Button size="sm" variant="secondary" onClick={() => setPicked(NEW_CHAT)}>
                New chat
              </Button>
            )}
          </div>
          {conversations.isError && (
            <p role="alert" className="mt-2 text-sm text-danger">
              {conversations.error.message}
            </p>
          )}
          <div className="mt-3 max-h-96 min-h-24 overflow-auto rounded bg-slate-50 p-3" aria-live="polite">
            {messages.isLoading && conversationId ? (
              <SkeletonRows count={2} />
            ) : messages.isError ? (
              <p role="alert" className="text-sm text-danger">
                {messages.error.message}
              </p>
            ) : msgs.length === 0 ? (
              <p className="text-sm text-muted">
                {canChat ? 'No messages yet. Ask what the agent did or why it priced a line.' : 'No messages yet.'}
              </p>
            ) : (
              <ul className="space-y-2">
                {msgs.map((m) => (
                  <li
                    key={m.id}
                    className={`max-w-[85%] whitespace-pre-wrap rounded px-3 py-2 text-sm ${
                      m.role === 'user' ? 'ml-auto bg-brand-subtle text-ink' : 'bg-white text-ink'
                    }`}
                  >
                    <span className="block text-xs text-muted">{m.role === 'user' ? 'You' : 'Agent'}</span>
                    {m.content}
                  </li>
                ))}
              </ul>
            )}
            {pending && (
              <p role="status" className="mt-2 flex items-center gap-2 text-sm text-muted">
                <Spinner /> The agent is working...
              </p>
            )}
          </div>
          {canChat ? (
            <form
              className="mt-3 flex items-end gap-2"
              onSubmit={(e) => {
                e.preventDefault()
                onSend()
              }}
            >
              <label className="min-w-0 flex-1 text-sm text-muted">
                Message to the agent
                <textarea
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  rows={2}
                  maxLength={4000}
                  className="mt-1 block w-full rounded border border-hairline bg-white px-2 py-1 text-sm text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
                />
              </label>
              <Button type="submit" loading={send.isPending} disabled={!text.trim()}>
                <Send className="h-4 w-4" aria-hidden="true" />
                Send
              </Button>
            </form>
          ) : (
            <p className="mt-3 text-xs text-muted">Read-only. {READ_ONLY_REASON}</p>
          )}
          {error && (
            <p role="alert" className="mt-2 text-sm text-danger">
              {error}
            </p>
          )}
        </div>
      )}
    </section>
  )
}
