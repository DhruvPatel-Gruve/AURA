import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Send, ArrowLeft, Loader2, Bot, User, CheckCircle2 } from 'lucide-react'
import { chatApi } from '@/api/chat.api'
import type { ChatMessage } from '@/api/chat.api'
import { LoadingSpinner } from '@/components/ui/LoadingSpinner'
import { Modal } from '@/components/ui/Modal'
import { MarkdownLite } from '@/components/ui/MarkdownLite'
import { cn } from '@/utils/cn'

function MessageBubble({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === 'user'
  return (
    <div className={cn('flex gap-3', isUser ? 'flex-row-reverse' : 'flex-row')}>
      <div className={cn(
        'h-8 w-8 rounded-full flex items-center justify-center shrink-0',
        isUser
          ? 'bg-accent text-white'
          : 'bg-sunken text-body',
      )}>
        {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
      </div>
      <div className={cn('max-w-[75%] space-y-1', isUser ? 'items-end' : 'items-start')}>
        <div className={cn(
          'rounded-lg px-4 py-2.5 text-sm leading-relaxed',
          isUser
            ? 'bg-accent text-white rounded-tr-sm'
            : 'bg-sunken text-ink rounded-tl-sm',
        )}>
          <MarkdownLite text={msg.content} />
        </div>
        {!isUser && msg.citations && msg.citations.length > 0 && (
          <p className="text-[10px] text-faint px-1 font-mono">
            Sources: {msg.citations.join(', ')}
          </p>
        )}
      </div>
    </div>
  )
}

function TypingIndicator() {
  return (
    <div className="flex gap-3">
      <div className="h-8 w-8 rounded-full bg-sunken flex items-center justify-center shrink-0">
        <Bot className="h-4 w-4 text-body" />
      </div>
      <div className="bg-sunken rounded-lg rounded-tl-sm px-4 py-3 flex items-center gap-1">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="h-2 w-2 rounded-full bg-faint animate-bounce"
            style={{ animationDelay: `${i * 0.15}s` }}
          />
        ))}
      </div>
    </div>
  )
}

export default function LiveChat() {
  const navigate      = useNavigate()
  const qc            = useQueryClient()
  const [input, setInput] = useState('')
  const [confirmClose, setConfirmClose] = useState(false)
  const [justClosed, setJustClosed]     = useState(false)
  const bottomRef     = useRef<HTMLDivElement>(null)

  const { data: historyData, isLoading: historyLoading } = useQuery({
    queryKey: ['chat', 'history'],
    queryFn:  () => chatApi.getHistory(),
    staleTime: 0,
  })

  const [localMessages, setLocalMessages] = useState<ChatMessage[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)

  const { mutate: sendMessage, isPending } = useMutation({
    mutationFn: (msg: string) => chatApi.send(msg),
    onMutate: (msg) => {
      setJustClosed(false)
      const userMsg: ChatMessage = { role: 'user', content: msg, timestamp: new Date().toISOString() }
      setLocalMessages((prev) => [...prev, userMsg])
    },
    onSuccess: (data) => {
      const assistantMsg: ChatMessage = {
        role:      'assistant',
        content:   data.reply,
        timestamp: data.timestamp,
        citations: data.citations,
      }
      setLocalMessages((prev) => [...prev, assistantMsg])
      setSessionId(data.session_id)
      void qc.invalidateQueries({ queryKey: ['chat', 'history'] })
    },
    onError: () => {
      setLocalMessages((prev) => [
        ...prev,
        { role: 'assistant', content: "Sorry, I couldn't reach the server. Please try again.", timestamp: new Date().toISOString() },
      ])
    },
  })

  const { mutate: closeConversation, isPending: isClosing } = useMutation({
    mutationFn: () => chatApi.close(),
    onSuccess: () => {
      setLocalMessages([])
      setSessionId(null)
      setConfirmClose(false)
      setJustClosed(true)
      void qc.invalidateQueries({ queryKey: ['chat', 'history'] })
    },
  })

  // Sync history into localMessages once loaded
  useEffect(() => {
    if (historyData) {
      setLocalMessages(historyData.messages)
      setSessionId(historyData.session_id)
    }
  }, [historyData])

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [localMessages, isPending])

  const handleSend = () => {
    const msg = input.trim()
    if (!msg || isPending) return
    setInput('')
    sendMessage(msg)
  }

  const handleKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  // localMessages is the render source of truth — it's seeded from
  // historyData on load/refetch (effect above) and updated optimistically
  // on send, so the user's own message appears the instant they hit Enter
  // instead of waiting for the post-reply history refetch to land.
  const displayMessages = localMessages

  return (
    <div className="flex flex-col h-[calc(100vh-64px)]">
      {/* Header */}
      <div className="flex items-center gap-3 px-6 py-4 border-b border-line bg-surface shrink-0">
        <button
          onClick={() => navigate('/enduser')}
          className="h-8 w-8 rounded-lg flex items-center justify-center hover:bg-sunken transition-colors"
        >
          <ArrowLeft className="h-4 w-4 text-faint" />
        </button>
        <div className="flex-1">
          <p className="text-sm font-semibold text-ink">
            AURA Assistant
          </p>
          <p className="text-xs text-body">
            Ask me anything about IT issues — I'm grounded in resolved ticket history.
          </p>
        </div>
        {displayMessages.length > 0 && sessionId && (
          <button
            onClick={() => setConfirmClose(true)}
            className="btn-ghost text-xs shrink-0"
          >
            Close conversation
          </button>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
        {historyLoading ? (
          <div className="flex justify-center py-12">
            <LoadingSpinner size="lg" />
          </div>
        ) : displayMessages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center pb-12">
            {justClosed ? (
              <>
                <CheckCircle2 className="h-10 w-10 text-emerald-500 mb-4" />
                <p className="text-sm font-semibold text-ink">Conversation closed</p>
                <p className="text-xs text-body mt-1 max-w-xs">
                  AURA won't remember that conversation anymore. Ask a new question to start fresh.
                </p>
              </>
            ) : (
              <>
                <Bot className="h-10 w-10 text-line mb-4" />
                <p className="text-sm font-semibold text-ink">Ask me anything</p>
                <p className="text-xs text-body mt-1 max-w-xs">
                  I can help with common IT issues like password resets, VPN setup, software installation, and more.
                </p>
              </>
            )}
            <div className="mt-5 flex flex-col gap-2 w-full max-w-xs">
              {[
                'How do I reset my password?',
                "My laptop won't connect to VPN",
                'How do I install software on a managed device?',
              ].map((q) => (
                <button
                  key={q}
                  onClick={() => { setInput(q) }}
                  className="text-left text-xs px-3 py-2.5 rounded-lg border border-line hover:border-accent hover:text-accent transition-colors text-body"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <>
            {displayMessages.map((msg, idx) => (
              <MessageBubble key={idx} msg={msg} />
            ))}
            {isPending && <TypingIndicator />}
            <div ref={bottomRef} />
          </>
        )}
      </div>

      {/* Input */}
      <div className="px-6 py-4 border-t border-line bg-surface shrink-0">
        <div className="flex gap-3 items-end">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKey}
            placeholder="Ask AURA a question… (Enter to send, Shift+Enter for new line)"
            rows={1}
            className="input-base flex-1 resize-none min-h-[40px] max-h-[120px] overflow-y-auto py-2.5"
            style={{ height: 'auto' }}
            onInput={(e) => {
              const el = e.currentTarget
              el.style.height = 'auto'
              el.style.height = `${Math.min(el.scrollHeight, 120)}px`
            }}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || isPending}
            className="h-10 w-10 rounded-lg bg-accent hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center transition-colors shrink-0"
          >
            {isPending
              ? <Loader2 className="h-4 w-4 text-white animate-spin" />
              : <Send className="h-4 w-4 text-white" />
            }
          </button>
        </div>
        <p className="text-[10px] text-faint mt-1.5">
          AURA answers based on resolved IT tickets. For urgent issues, submit a ticket instead.
        </p>
      </div>

      {/* Confirm close */}
      <Modal open={confirmClose} onClose={() => setConfirmClose(false)} title="Close conversation?" size="sm">
        <div className="space-y-4">
          <p className="text-sm text-body">
            AURA will forget everything discussed in this conversation. Your next message will start a
            fresh resolution with no memory of this one. The transcript itself isn't deleted.
          </p>
          <div className="flex justify-end gap-2">
            <button onClick={() => setConfirmClose(false)} className="btn-ghost">Cancel</button>
            <button
              onClick={() => closeConversation()}
              disabled={isClosing}
              className="btn-primary"
            >
              {isClosing ? <LoadingSpinner size="sm" className="text-white" /> : 'Close conversation'}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
