import React, { useEffect, useState } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'

interface Task {
  timestamp: string
  people: string[]
  client: string
  summary: string
  fullMessage: string
  status: string
  dueDate: string
  botNotes: string
}

interface Message {
  id: string
  content: string
  sender: 'user' | 'bot'
  timestamp: Date
}

const SPREADSHEET_URL = 'https://docs.google.com/spreadsheets/d/1XBPrffKlIEI_htPNWbBNo2dk-crt62323luClLYFyDQ/edit?gid=0#gid=0'

export const TaskManagerApp: React.FC = () => {
  const [tasks, setTasks] = useState<Task[]>([])
  const [messages, setMessages] = useState<Message[]>([])
  const [inputValue, setInputValue] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [activeView, setActiveView] = useState<'chat' | 'list'>('chat')
  const [statusFilter, setStatusFilter] = useState<string>('')

  // Load tasks from the backend
  async function loadTasks() {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      if (statusFilter) params.set('status', statusFilter)
      const r = await fetch(`${API_BASE}/tasks?${params.toString()}`)
      if (!r.ok) throw new Error('Failed to load tasks')
      const data = await r.json()
      setTasks(data.tasks || [])
    } catch (e: any) {
      setError(e?.message || 'Failed to load tasks')
    } finally {
      setLoading(false)
    }
  }

  // Submit a new task via chat
  async function handleSubmit() {
    if (!inputValue.trim()) return

    const userMessage: Message = {
      id: Date.now().toString(),
      content: inputValue.trim(),
      sender: 'user',
      timestamp: new Date(),
    }

    setMessages((prev) => [...prev, userMessage])
    const messageContent = inputValue.trim()
    setInputValue('')
    setLoading(true)
    setError(null)

    try {
      const response = await fetch(`${API_BASE}/tasks/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: messageContent,
          userId: 'web-user',
        }),
      })

      const data = await response.json()

      if (data.success) {
        const botMessage: Message = {
          id: (Date.now() + 1).toString(),
          content: data.response,
          sender: 'bot',
          timestamp: new Date(),
        }
        setMessages((prev) => [...prev, botMessage])
      } else {
        const errorMessage: Message = {
          id: (Date.now() + 1).toString(),
          content: data.error || 'Sorry, I encountered an error processing your request. Please try again.',
          sender: 'bot',
          timestamp: new Date(),
        }
        setMessages((prev) => [...prev, errorMessage])
      }
    } catch (e: any) {
      console.error('Error calling chat API:', e)
      const errorMessage: Message = {
        id: (Date.now() + 1).toString(),
        content: "Sorry, I'm having trouble connecting right now. Please try again.",
        sender: 'bot',
        timestamp: new Date(),
      }
      setMessages((prev) => [...prev, errorMessage])
    } finally {
      setLoading(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  useEffect(() => {
    if (activeView === 'list') {
      loadTasks()
    }
  }, [activeView, statusFilter])

  const formatDate = (dateStr: string) => {
    if (!dateStr) return '—'
    try {
      return new Date(dateStr).toLocaleDateString()
    } catch {
      return dateStr
    }
  }

  const getStatusStyle = (status: string) => {
    switch (status) {
      case 'Complete':
        return { background: '#e8f5e9', color: '#2e7d32', border: '1px solid #a5d6a7' }
      case 'In Progress':
        return { background: '#fff3e0', color: '#ef6c00', border: '1px solid #ffcc80' }
      default:
        return { background: '#fafafa', color: '#616161', border: '1px solid #e0e0e0' }
    }
  }

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>Task Manager</h2>
        <a
          href={SPREADSHEET_URL}
          target="_blank"
          rel="noopener noreferrer"
          style={{ color: '#000', textDecoration: 'underline' }}
        >
          Open Spreadsheet ↗
        </a>
      </div>

      {/* View Toggle */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
        <button
          onClick={() => setActiveView('chat')}
          style={{
            padding: '8px 16px',
            background: activeView === 'chat' ? '#000' : '#fff',
            color: activeView === 'chat' ? '#fff' : '#000',
            border: '2px solid #000',
            cursor: 'pointer',
            fontWeight: 'bold',
          }}
        >
          Add Tasks
        </button>
        <button
          onClick={() => setActiveView('list')}
          style={{
            padding: '8px 16px',
            background: activeView === 'list' ? '#000' : '#fff',
            color: activeView === 'list' ? '#fff' : '#000',
            border: '2px solid #000',
            cursor: 'pointer',
            fontWeight: 'bold',
          }}
        >
          View Tasks
        </button>
      </div>

      {error && <div style={{ color: 'red', marginBottom: 12 }}>{error}</div>}

      {/* Chat View */}
      {activeView === 'chat' && (
        <div>
          <p style={{ color: '#666', marginBottom: 16 }}>
            Add to-do list items below. You can add one at a time or multiple items separated by bullet points, dashes, or "AND".
          </p>

          {/* Chat Messages */}
          <div
            style={{
              background: '#f5f5f5',
              borderRadius: 8,
              padding: 16,
              height: 320,
              overflowY: 'auto',
              marginBottom: 16,
            }}
          >
            {messages.length === 0 ? (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#999' }}>
                Start by adding your to-do items below.
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {messages.map((message) => (
                  <div
                    key={message.id}
                    style={{
                      display: 'flex',
                      justifyContent: message.sender === 'user' ? 'flex-end' : 'flex-start',
                    }}
                  >
                    <div
                      style={{
                        maxWidth: '80%',
                        padding: 12,
                        borderRadius: 8,
                        background: message.sender === 'user' ? '#000' : '#fff',
                        color: message.sender === 'user' ? '#fff' : '#000',
                        border: message.sender === 'bot' ? '1px solid #e0e0e0' : 'none',
                      }}
                    >
                      <p style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{message.content}</p>
                      <span style={{ fontSize: 11, opacity: 0.7, marginTop: 8, display: 'block' }}>
                        {message.timestamp.toLocaleTimeString()}
                      </span>
                    </div>
                  </div>
                ))}
                {loading && (
                  <div style={{ display: 'flex', justifyContent: 'flex-start' }}>
                    <div style={{ background: '#fff', border: '1px solid #e0e0e0', padding: 12, borderRadius: 8 }}>
                      <div style={{ display: 'flex', gap: 4 }}>
                        <span style={{ width: 8, height: 8, background: '#999', borderRadius: '50%', animation: 'bounce 0.6s infinite' }} />
                        <span style={{ width: 8, height: 8, background: '#999', borderRadius: '50%', animation: 'bounce 0.6s infinite 0.1s' }} />
                        <span style={{ width: 8, height: 8, background: '#999', borderRadius: '50%', animation: 'bounce 0.6s infinite 0.2s' }} />
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Input */}
          <textarea
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Add to-do list items here, one at a time or separated by bullet points or dashes"
            style={{
              width: '100%',
              minHeight: 100,
              padding: 12,
              fontSize: 14,
              border: '2px solid #e0e0e0',
              borderRadius: 4,
              resize: 'vertical',
              fontFamily: 'inherit',
              boxSizing: 'border-box',
            }}
            disabled={loading}
          />
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 12 }}>
            <button
              onClick={handleSubmit}
              disabled={!inputValue.trim() || loading}
              style={{
                padding: '10px 24px',
                background: !inputValue.trim() || loading ? '#ccc' : '#000',
                color: '#fff',
                border: 'none',
                cursor: !inputValue.trim() || loading ? 'not-allowed' : 'pointer',
                fontWeight: 'bold',
                fontSize: 14,
              }}
            >
              Submit
            </button>
          </div>
        </div>
      )}

      {/* List View */}
      {activeView === 'list' && (
        <div>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 16 }}>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              style={{ padding: '8px 12px', border: '1px solid #ccc' }}
            >
              <option value="">All Statuses</option>
              <option value="Not Started">Not Started</option>
              <option value="In Progress">In Progress</option>
              <option value="Complete">Complete</option>
            </select>
            <button onClick={loadTasks} disabled={loading} style={{ padding: '8px 16px' }}>
              Refresh
            </button>
          </div>

          {loading && <div>Loading...</div>}

          {!loading && tasks.length === 0 && (
            <div style={{ padding: 24, border: '1px dashed #ccc', color: '#666', textAlign: 'center' }}>
              No tasks found. Add some tasks using the "Add Tasks" view.
            </div>
          )}

          {!loading && tasks.length > 0 && (
            <div>
              {/* Header */}
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: '1fr 100px 100px 100px 120px',
                  gap: 12,
                  padding: '8px 12px',
                  borderBottom: '2px solid #000',
                  fontWeight: 'bold',
                }}
              >
                <div>Task</div>
                <div>People</div>
                <div>Client</div>
                <div>Status</div>
                <div>Due Date</div>
              </div>

              {/* Rows */}
              {tasks.map((task, idx) => (
                <div
                  key={idx}
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '1fr 100px 100px 100px 120px',
                    gap: 12,
                    padding: '12px',
                    borderBottom: '1px solid #e0e0e0',
                    alignItems: 'center',
                  }}
                >
                  <div>
                    <div style={{ fontWeight: 500 }}>{task.summary}</div>
                    {task.fullMessage && task.fullMessage !== task.summary && (
                      <div style={{ fontSize: 12, color: '#666', marginTop: 4 }}>
                        {task.fullMessage.length > 100 ? task.fullMessage.slice(0, 100) + '...' : task.fullMessage}
                      </div>
                    )}
                  </div>
                  <div style={{ fontSize: 13 }}>{task.people?.join(', ') || '—'}</div>
                  <div style={{ fontSize: 13 }}>{task.client || '—'}</div>
                  <div>
                    <span
                      style={{
                        ...getStatusStyle(task.status),
                        padding: '4px 8px',
                        borderRadius: 4,
                        fontSize: 12,
                        display: 'inline-block',
                      }}
                    >
                      {task.status || 'Not Started'}
                    </span>
                  </div>
                  <div style={{ fontSize: 13 }}>{formatDate(task.dueDate)}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <style>{`
        @keyframes bounce {
          0%, 100% { transform: translateY(0); }
          50% { transform: translateY(-4px); }
        }
      `}</style>
    </div>
  )
}
