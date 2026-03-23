import { useState, useRef, useEffect } from 'react'
import { chatApi } from '../api/client'
import { Send, Bot, User, Loader2 } from 'lucide-react'

interface Message {
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
}

const QUICK_ACTIONS = [
  'Trigger a new analysis',
  'What are the pending proposals?',
  'Show my risk exposure',
  'How are the agents performing?',
  "What's the market status?",
  'Show open positions',
]

const WELCOME: Message = {
  role: 'assistant',
  content: "Hello! I'm Sol, your trading orchestrator. I manage your AI trading agents and ensure all trades are confirmed with you before execution.\n\nHow can I help you today?",
  timestamp: new Date(),
}

export default function ChatInterface() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(true)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    chatApi.getHistory(20)
      .then(res => {
        const history: Message[] = res.data.map((m: any) => ({
          role: m.role,
          content: m.content,
          timestamp: new Date(m.timestamp),
        }))
        setMessages(history.length > 0 ? history : [WELCOME])
      })
      .catch(() => setMessages([WELCOME]))
      .finally(() => setHistoryLoading(false))
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const send = async (text: string) => {
    if (!text.trim() || loading) return
    const userMsg: Message = { role: 'user', content: text, timestamp: new Date() }
    setMessages(m => [...m, userMsg])
    setInput('')
    setLoading(true)

    try {
      const res = await chatApi.send(text)
      setMessages(m => [...m, {
        role: 'assistant',
        content: res.data.response,
        timestamp: new Date(),
      }])
    } catch (e) {
      setMessages(m => [...m, {
        role: 'assistant',
        content: 'Sorry, I encountered an error. Please try again.',
        timestamp: new Date(),
      }])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col" style={{ height: 'calc(100dvh - 130px)' }}>
      <h1 className="text-2xl font-bold text-white mb-4">Chat with Sol</h1>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto space-y-4 mb-4 scrollbar-thin pr-2">
        {historyLoading && (
          <div className="flex items-center justify-center h-32 text-gray-500 gap-2">
            <Loader2 size={16} className="animate-spin" />
            <span className="text-sm">Loading conversation...</span>
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`flex gap-3 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            {msg.role === 'assistant' && (
              <div className="w-8 h-8 rounded-full bg-sol-accent/20 border border-sol-accent/40 flex items-center justify-center flex-shrink-0 mt-1">
                <Bot size={16} className="text-sol-accent" />
              </div>
            )}
            <div className={`max-w-[75%] rounded-2xl px-4 py-3 ${
              msg.role === 'user'
                ? 'bg-sol-accent text-white rounded-br-sm'
                : 'bg-sol-card border border-sol-border text-gray-200 rounded-bl-sm'
            }`}>
              <p className="text-sm whitespace-pre-wrap leading-relaxed">{msg.content}</p>
              <p className="text-xs opacity-40 mt-1 text-right">
                {msg.timestamp.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}
              </p>
            </div>
            {msg.role === 'user' && (
              <div className="w-8 h-8 rounded-full bg-gray-700 flex items-center justify-center flex-shrink-0 mt-1">
                <User size={16} className="text-gray-300" />
              </div>
            )}
          </div>
        ))}

        {loading && (
          <div className="flex gap-3">
            <div className="w-8 h-8 rounded-full bg-sol-accent/20 border border-sol-accent/40 flex items-center justify-center">
              <Bot size={16} className="text-sol-accent" />
            </div>
            <div className="bg-sol-card border border-sol-border rounded-2xl rounded-bl-sm px-4 py-3">
              <div className="flex gap-1">
                {[0,1,2].map(i => (
                  <span key={i} className="w-2 h-2 bg-gray-500 rounded-full animate-bounce" style={{animationDelay: `${i*150}ms`}} />
                ))}
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Quick Actions */}
      <div className="flex gap-2 mb-3 flex-wrap">
        {QUICK_ACTIONS.map(q => (
          <button
            key={q}
            onClick={() => send(q)}
            className="text-xs bg-gray-800 hover:bg-gray-700 border border-sol-border text-gray-400 hover:text-white px-3 py-1.5 rounded-full transition-colors"
          >
            {q}
          </button>
        ))}
      </div>

      {/* Input */}
      <form onSubmit={e => { e.preventDefault(); send(input) }} className="flex gap-3">
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder="Ask Sol anything about your portfolio, agents, or market..."
          className="flex-1 bg-sol-card border border-sol-border rounded-xl px-4 py-3 text-white text-sm focus:outline-none focus:border-sol-accent placeholder-gray-600"
        />
        <button
          type="submit"
          disabled={!input.trim() || loading}
          className="bg-sol-accent hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white p-3 rounded-xl transition-colors"
        >
          <Send size={18} />
        </button>
      </form>
    </div>
  )
}
