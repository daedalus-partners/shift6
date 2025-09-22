import React, { useEffect, useMemo, useRef, useState } from 'react'
import axios from 'axios'

type Client = { id: number; slug: string; name: string }
type KnowledgeFile = { id: number; source_type: string; filename?: string; text?: string; uploaded_at: string }
type Style = { id: number; label: string; text: string; created_at: string }
type Sample = { id: number; source?: string; text: string; created_at: string }

const apiBase = ''
const dbg = (...args: any[]) => { try { console.log('[upload-debug]', ...args) } catch { /* no-op */ } }
const post = async (url: string, body: FormData, onProgress: (pct: number) => void) => {
  dbg('POST start', url, 'size', [...body.entries()].reduce((n, [k, v]) => n + (v instanceof File ? v.size : 0), 0))
  return axios.post(url, body, {
    onUploadProgress: (e) => {
      if (e.total) onProgress(Math.round((e.loaded / e.total) * 100))
    },
    headers: { 'X-Requested-With': 'XMLHttpRequest' },
    validateStatus: () => true,
  })
}
const mk = (path: string) => `${apiBase}${path}`

export const QuotesApp: React.FC = () => {
  const [health, setHealth] = useState<string>('checking…')
  const [clients, setClients] = useState<Client[]>([])
  const [clientId, setClientId] = useState<number | null>(null)
  const [knowledge, setKnowledge] = useState<KnowledgeFile[]>([])
  const [styles, setStyles] = useState<Style[]>([])
  const [samples, setSamples] = useState<Sample[]>([])
  const [note, setNote] = useState<string>('')
  const [styleLabel, setStyleLabel] = useState('')
  const [styleText, setStyleText] = useState('')
  const [sampleSource, setSampleSource] = useState('')
  const [sampleText, setSampleText] = useState('')
  const [query, setQuery] = useState('')
  const [response, setResponse] = useState('')
  const eventSrcRef = useRef<EventSource | null>(null)
  const [dragOver, setDragOver] = useState<boolean>(false)
  const [messages, setMessages] = useState<Array<{id?:number; role:'user'|'assistant'|'system'; content:string; created_at?:string}>>([])
  const [typing, setTyping] = useState<boolean>(false)
  const [errorMsg, setErrorMsg] = useState<string>('')
  const [useWeb, setUseWeb] = useState<boolean>(false)

  useEffect(() => {
    fetch(mk('/health')).then(r => r.json()).then(d => setHealth(d.status ?? 'ok')).catch(() => setHealth('error'))
  }, [])

  useEffect(() => {
    fetch(mk('/clients/')).then(r => r.json()).then((list: Client[]) => {
      setClients(list)
      if (list.length && !clientId) setClientId(list[0].id)
    }).catch(() => {})
  }, [])

  useEffect(() => {
    if (!clientId) return
    Promise.all([
      fetch(mk(`/knowledge/${clientId}`)).then(r => r.json()),
      fetch(mk(`/styles/${clientId}`)).then(r => r.json()),
      fetch(mk(`/samples/${clientId}`)).then(r => r.json()),
    ]).then(([k, s, q]) => {
      setKnowledge(k)
      setStyles(s)
      setSamples(q)
    }).catch(() => {})
    // load recent chat
    fetch(mk(`/chat/${clientId}/last`)).then(r => r.json()).then((list:any[]) => {
      // server returns newest first; show oldest first
      setMessages((list || []).slice().reverse().map(m => ({ id:m.id, role:m.role, content:m.content, created_at:m.created_at })))
    }).catch(() => {})
  }, [clientId])

  const onAddNote = async () => {
    if (!clientId || !note.trim()) return
    const res = await fetch(mk(`/knowledge/${clientId}/notes`), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: note }) })
    if (res.ok) {
      setNote('')
      const k = await fetch(mk(`/knowledge/${clientId}`)).then(r => r.json())
      setKnowledge(k)
    }
  }

  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState<number>(0)
  type UploadItem = { id: string; name: string; file: File; progress: number; status: 'queued' | 'uploading' | 'done' | 'duplicate' | 'error' }
  const [uploadQueue, setUploadQueue] = useState<UploadItem[]>([])
  const [processingQueue, setProcessingQueue] = useState<boolean>(false)
  const queuedOrUploading = useMemo(() => uploadQueue.some(it => it.status === 'queued' || it.status === 'uploading'), [uploadQueue])
  const overallProgress = useMemo(() => {
    const active = uploadQueue.filter(it => it.status === 'queued' || it.status === 'uploading')
    if (!active.length) return 0
    const sum = active.reduce((acc, it) => acc + it.progress, 0)
    return Math.round(sum / active.length)
  }, [uploadQueue])

  // live refs to avoid stale closures when starting the async processor
  const uploadQueueRef = useRef<UploadItem[]>([])
  useEffect(() => { uploadQueueRef.current = uploadQueue }, [uploadQueue])
  const clientIdRef = useRef<number | null>(null)
  useEffect(() => { clientIdRef.current = clientId }, [clientId])

  useEffect(() => {
    if (!processingQueue && uploadQueue.some(it => it.status === 'queued')) {
      void processUploadQueue()
    }
  }, [uploadQueue, processingQueue])

  const onUploadFile = async (f: File) => {
    if (!clientId) return
    dbg('single-file upload selected', f.name, f.size)
    setUploading(true)
    setUploadProgress(0)
    try {
      const form = new FormData()
      form.append('file', f)
      const res = await post(mk(`/knowledge/${clientId}/upload`), form, (p)=>setUploadProgress(p))
      dbg('single-file upload response', res.status)
      if (res.status === 201 || res.status === 200) {
        const k = await fetch(mk(`/knowledge/${clientId}`)).then(r => r.json())
        setKnowledge(k)
        setTimeout(() => { setUploading(false); setUploadProgress(0) }, 800)
      } else if (res.status === 409) {
        alert('Duplicate file detected. Skipping upload.')
      } else {
        alert('Upload failed')
      }
    } finally {
      setUploading(false)
      setUploadProgress(0)
    }
  }

  const onDropFiles = async (files: FileList | File[]) => {
    if (!clientId) {
      alert('Select a client first')
      return
    }
    const list = Array.from(files as FileList)
    if (!list.length) return
    dbg('queueing files', list.map(f => `${f.name}(${f.size})`))
    const newItems: UploadItem[] = list.map((f) => ({ id: `${Date.now()}-${f.name}-${Math.random().toString(36).slice(2,8)}`, name: f.name, file: f, progress: 0, status: 'queued' }))
    setUploadQueue(prev => [...prev, ...newItems])
    // processor will auto-start via useEffect watching uploadQueue
  }

  const processUploadQueue = async () => {
    if (processingQueue) return
    setProcessingQueue(true)
    try {
      // process while there is any queued item
      // eslint-disable-next-line no-constant-condition
      while (true) {
        const snapshot = uploadQueueRef.current
        const idx = snapshot.findIndex(it => it.status === 'queued')
        if (idx === -1) break
        const nextId = snapshot[idx].id
        const nextFile = snapshot[idx].file
        setUploadQueue(prev => prev.map(it => it.id === nextId ? { ...it, status: 'uploading', progress: 0 } : it))
        // ensure client still selected
        if (!clientIdRef.current) {
          // cannot find original File object; skip gracefully
          setUploadQueue(prev => prev.map(it => it.id === nextId ? { ...it, status: 'error' } : it))
          continue
        }

        // upload this file with progress updating this queue item
        try {
          const form = new FormData()
          form.append('file', nextFile)
          dbg('uploading', nextFile.name, nextFile.size)
          const res = await post(mk(`/knowledge/${clientIdRef.current}/upload`), form, (pct)=>{
            setUploadQueue(prev => prev.map(it => it.id === nextId ? { ...it, progress: pct } : it))
          })
          dbg('upload response', nextFile.name, res.status)
          if (res.status === 201 || res.status === 200) {
            setUploadQueue(prev => prev.map(it => it.id === nextId ? { ...it, status: 'done', progress: 100 } : it))
            setTimeout(() => setUploadQueue(prev => prev.filter(it => it.id !== nextId)), 1200)
            // refresh list after each success
            const k = await fetch(mk(`/knowledge/${clientIdRef.current}`)).then(r => r.json())
            setKnowledge(k)
          } else if (res.status === 409) {
            setUploadQueue(prev => prev.map(it => it.id === nextId ? { ...it, status: 'duplicate', progress: 100 } : it))
            setTimeout(() => setUploadQueue(prev => prev.filter(it => it.id !== nextId)), 1400)
          } else {
            setUploadQueue(prev => prev.map(it => it.id === nextId ? { ...it, status: 'error' } : it))
            setTimeout(() => setUploadQueue(prev => prev.filter(it => it.id !== nextId)), 1600)
          }
        } catch (e) {
          dbg('upload error', (e as any)?.message || e)
          setUploadQueue(prev => prev.map(it => it.id === nextId ? { ...it, status: 'error' } : it))
          setTimeout(() => setUploadQueue(prev => prev.filter(it => it.id !== nextId)), 1600)
        }
      }
    } finally {
      setProcessingQueue(false)
    }
  }

  const onDeleteKnowledge = async (id: number) => {
    if (!clientId) return
    await fetch(mk(`/knowledge/${clientId}/${id}`), { method: 'DELETE' })
    const k = await fetch(mk(`/knowledge/${clientId}`)).then(r => r.json())
    setKnowledge(k)
  }

  const onAddStyle = async () => {
    if (!clientId || !styleText.trim()) return
    const res = await fetch(mk(`/styles/${clientId}`), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ label: styleLabel || 'style', text: styleText }) })
    if (res.ok) {
      setStyleLabel(''); setStyleText('')
      const s = await fetch(mk(`/styles/${clientId}`)).then(r => r.json())
      setStyles(s)
    }
  }

  const onDeleteStyle = async (id: number) => {
    if (!clientId) return
    await fetch(mk(`/styles/${clientId}/${id}`), { method: 'DELETE' })
    const s = await fetch(mk(`/styles/${clientId}`)).then(r => r.json())
    setStyles(s)
  }

  const onAddSample = async () => {
    if (!clientId || !sampleText.trim()) return
    const res = await fetch(mk(`/samples/${clientId}`), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ source: sampleSource || '', text: sampleText }) })
    if (res.ok) {
      setSampleSource(''); setSampleText('')
      const q = await fetch(mk(`/samples/${clientId}`)).then(r => r.json())
      setSamples(q)
    }
  }

  const onDeleteSample = async (id: number) => {
    if (!clientId) return
    await fetch(mk(`/samples/${clientId}/${id}`), { method: 'DELETE' })
    const q = await fetch(mk(`/samples/${clientId}`)).then(r => r.json())
    setSamples(q)
  }

  const onSend = async () => {
    if (!clientId || !query.trim()) return
    eventSrcRef.current?.close()
    setResponse('')
    setTyping(true)
    // optimistic append user message
    const text = query.trim()
    setMessages(prev => [...prev, { role:'user', content: text }])
    setQuery('')
    const refreshChatLater = () => {
      if (!clientId) return
      fetch(mk(`/chat/${clientId}/last`)).then(r => r.json()).then((list:any[]) => {
        setMessages((list || []).slice().reverse().map(m => ({ id:m.id, role:m.role, content:m.content, created_at:m.created_at })))
        setTyping(false)
      }).catch(() => setTyping(false))
    }
    try {
      const url = mk(`/generate/${clientId}?q=${encodeURIComponent(text)}${useWeb ? '&include_web=1' : ''}`)
      const es = new EventSource(url)
      eventSrcRef.current = es
      let gotChunk = false
      es.onmessage = (e) => {
        gotChunk = true
        // handle plain text or JSON
        try {
          const data = JSON.parse(e.data)
          if (data.type === 'content_block_delta' && data.delta?.text) {
            setResponse(prev => prev + data.delta.text)
            return
          }
        } catch {}
        setResponse(prev => prev + (e.data || ''))
      }
      es.onerror = async () => {
        es.close()
        if (!gotChunk) {
          // Fallback to non-streaming
          const resp = await fetch(mk(`/generate/full/${clientId}?q=${encodeURIComponent(text)}${useWeb ? '&include_web=1' : ''}`))
          if (resp.ok) {
            const j = await resp.json()
            setResponse(String(j.content || ''))
          } else {
            setErrorMsg('Error generating response')
          }
        }
        setTimeout(refreshChatLater, 600)
      }
    } catch (e) {
      // direct fallback
      const resp = await fetch(mk(`/generate/full/${clientId}?q=${encodeURIComponent(text)}${useWeb ? '&include_web=1' : ''}`))
      if (resp.ok) {
        const j = await resp.json()
        setResponse(String(j.content || ''))
      } else {
        setErrorMsg('Error generating response')
      }
      setTimeout(refreshChatLater, 600)
    }
  }

  const uploaderRef = useRef<HTMLInputElement | null>(null)

  const addClientFlow = async () => {
    const name = window.prompt('Client name?')
    if (!name) return
    const suggested = name.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '') || 'client'
    const slug = window.prompt('Client slug?', suggested) || suggested
    const res = await fetch(mk('/clients/'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, slug }) })
    if (!res.ok) {
      alert('Could not create client (may already exist).')
    }
    const list: Client[] = await fetch(mk('/clients/')).then(r=>r.json())
    setClients(list)
    const created = list.find(c=>c.slug===slug)
    if (created) setClientId(created.id)
  }

  return (
    <div style={{ fontFamily: 'system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif', color: '#000', background: '#fff', minHeight: '100vh' }}>
      <header style={{ borderBottom: '1px solid #9e9e9e', padding: '16px 24px', display: 'flex', alignItems: 'baseline', gap: 16 }}>
        <h1 style={{ margin: 0, fontWeight: 600, flex: 1 }}>Shift6 – Client Quote Generator</h1>
        <div style={{ fontSize: 14, color: '#555' }}>API health: {health}</div>
        <select value={String(clientId ?? '')} onChange={(e) => { const v=e.target.value; if (v==='__add__'){ void addClientFlow(); } else { setClientId(Number(v)); } }} style={{ padding: '6px 10px', border: '1px solid #000', background: '#fff' }}>
          {clients.map(c => <option key={c.id} value={String(c.id)}>{c.name}</option>)}
          <option value="__add__">+ Add client…</option>
        </select>
      </header>
      <main style={{ padding: 24 }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16 }}>
          <section style={{ border: '1px solid #000', padding: 12 }}>
            <h3 style={{ marginTop: 0 }}>Knowledge</h3>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <input value={note} onChange={e => setNote(e.target.value)} placeholder="Add note…" style={{ flex: 1, border: '1px solid #000', padding: '6px 8px' }} />
              <button onClick={onAddNote} style={{ border: '1px solid #000', background: '#fff', padding: '6px 10px' }}>Add</button>
              <input ref={uploaderRef} type="file" multiple style={{ display: 'none' }} onChange={e => { if (e.target.files) onDropFiles(e.target.files); (e.target as HTMLInputElement).value = '' }} />
              <button onClick={() => uploaderRef.current?.click()} style={{ border: '1px solid #000', background: '#fff', padding: '6px 10px' }}>Upload</button>
              <button onClick={() => { dbg('manual start uploads (header)'); void processUploadQueue() }} style={{ border: '1px solid #000', background: '#fff', padding: '6px 10px' }}>Start uploads</button>
            </div>
            <div
              onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => { e.preventDefault(); setDragOver(false); if (e.dataTransfer?.files?.length) onDropFiles(e.dataTransfer.files) }}
              style={{
                border: '1px dashed #000',
                padding: '16px',
                marginTop: 8,
                textAlign: 'center',
                background: dragOver ? '#f5f5f5' : '#fff',
                color: '#000',
                cursor: 'copy',
                userSelect: 'none',
              }}
            >
              {(queuedOrUploading || processingQueue || uploading)
                ? `Uploading… ${overallProgress || uploadProgress}%`
                : 'Drag & drop files here (multi-file supported)'}
            </div>
            {uploadQueue.length > 0 && (
              <div style={{ marginTop: 8 }}>
                <div style={{ fontSize: 12, color: '#555', marginBottom: 4 }}>Upload queue</div>
                <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
                  {uploadQueue.map(item => (
                    <li key={item.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0' }}>
                      <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.name}</span>
                      <span style={{ fontSize: 12, minWidth: 80, textAlign: 'right' }}>{item.status}</span>
                      <div style={{ width: 120, height: 6, border: '1px solid #000' }}>
                        <div style={{ width: `${item.progress}%`, height: '100%', background: '#000' }} />
                      </div>
                    </li>
                  ))}
                </ul>
                {uploadQueue.some(it => it.status === 'queued') && (
                  <div style={{ marginTop: 6, display: 'flex', gap: 8 }}>
                    <button onClick={() => { dbg('manual start uploads'); void processUploadQueue() }} style={{ border: '1px solid #000', background: '#fff', padding: '4px 8px' }}>Start uploads</button>
                    <button onClick={() => setUploadQueue([])} style={{ border: '1px solid #000', background: '#fff', padding: '4px 8px' }}>Clear queue</button>
                  </div>
                )}
              </div>
            )}
            <ul style={{ listStyle: 'none', padding: 0, marginTop: 12 }}>
              {knowledge.map(k => (
                <li key={k.id} style={{ display: 'flex', justifyContent: 'space-between', borderTop: '1px solid #9e9e9e', padding: '8px 0' }}>
                  <span>{k.source_type === 'note' ? (k.text?.slice(0, 40) || 'note') : (k.filename || 'file')}</span>
                  <button onClick={() => onDeleteKnowledge(k.id)} style={{ border: '1px solid #000', background: '#fff', padding: '4px 8px' }}>Delete</button>
                </li>
              ))}
            </ul>
          </section>
          <section style={{ border: '1px solid #000', padding: 12 }}>
            <h3 style={{ marginTop: 0 }}>Style</h3>
            <div style={{ display: 'flex', gap: 8 }}>
              <input value={styleLabel} onChange={e => setStyleLabel(e.target.value)} placeholder="Label" style={{ flex: 0.6, border: '1px solid #000', padding: '6px 8px' }} />
              <input value={styleText} onChange={e => setStyleText(e.target.value)} placeholder="Snippet…" style={{ flex: 1, border: '1px solid #000', padding: '6px 8px' }} />
              <button onClick={onAddStyle} style={{ border: '1px solid #000', background: '#fff', padding: '6px 10px' }}>Add</button>
            </div>
            <ul style={{ listStyle: 'none', padding: 0, marginTop: 12 }}>
              {styles.map(s => (
                <li key={s.id} style={{ display: 'flex', justifyContent: 'space-between', borderTop: '1px solid #9e9e9e', padding: '8px 0' }}>
                  <span>{s.label}: {s.text}</span>
                  <button onClick={() => onDeleteStyle(s.id)} style={{ border: '1px solid #000', background: '#fff', padding: '4px 8px' }}>Delete</button>
                </li>
              ))}
            </ul>
          </section>
          <section style={{ border: '1px solid #000', padding: 12 }}>
            <h3 style={{ marginTop: 0 }}>Sample Quotes</h3>
            <div style={{ display: 'flex', gap: 8 }}>
              <input value={sampleSource} onChange={e => setSampleSource(e.target.value)} placeholder="Source (optional)" style={{ flex: 0.6, border: '1px solid #000', padding: '6px 8px' }} />
              <input value={sampleText} onChange={e => setSampleText(e.target.value)} placeholder="Quote…" style={{ flex: 1, border: '1px solid #000', padding: '6px 8px' }} />
              <button onClick={onAddSample} style={{ border: '1px solid #000', background: '#fff', padding: '6px 10px' }}>Add</button>
            </div>
            <ul style={{ listStyle: 'none', padding: 0, marginTop: 12 }}>
              {samples.map(s => (
                <li key={s.id} style={{ display: 'flex', justifyContent: 'space-between', borderTop: '1px solid #9e9e9e', padding: '8px 0' }}>
                  <span>{s.source ? `${s.source}: ` : ''}{s.text}</span>
                  <button onClick={() => onDeleteSample(s.id)} style={{ border: '1px solid #000', background: '#fff', padding: '4px 8px' }}>Delete</button>
                </li>
              ))}
            </ul>
          </section>
        </div>
        <section style={{ border: '1px solid #000', padding: 12, marginTop: 16 }}>
          <h3 style={{ marginTop: 0 }}>Chat</h3>
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start', marginBottom: 8 }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <input type="checkbox" checked={useWeb} onChange={e=>setUseWeb(e.target.checked)} />
              <span style={{ fontSize: 12 }}>Web search</span>
            </label>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
            <textarea value={query} onChange={e => setQuery(e.target.value)} placeholder="Paste text or ask for a quote…" style={{ flex: 1, border: '1px solid #000', padding: '6px 8px', minHeight: 240, resize: 'both' }} onKeyDown={(e)=>{ if(e.key==='Enter' && !e.shiftKey){ e.preventDefault(); void onSend(); } }} />
            <button onClick={onSend} style={{ border: '1px solid #000', background: '#fff', padding: '6px 10px' }}>Send</button>
          </div>
          <div style={{ borderTop: '1px solid #9e9e9e', marginTop: 12, paddingTop: 12 }}>
            <div style={{ marginBottom: 8, fontSize: 12, color: '#555' }}>Recent messages</div>
            <div style={{ maxHeight: 240, overflowY: 'auto', border: '1px solid #9e9e9e', padding: 8 }}>
              {messages.map((m, i) => (
                <div key={i} style={{ marginBottom: 8 }}>
                  <div style={{ fontSize: 12, color: '#999' }}>{m.role}</div>
                  <div style={{ whiteSpace: 'pre-wrap' }}>{m.content}</div>
                </div>
              ))}
              {typing && (<div style={{ fontStyle: 'italic', color: '#555' }}>Assistant is typing…</div>)}
              {response && (
                <div>
                  <div style={{ fontSize: 12, color: '#999' }}>assistant (stream)</div>
                  <div style={{ whiteSpace: 'pre-wrap' }}>{response}</div>
                </div>
              )}
            </div>
            {errorMsg && <div style={{ marginTop: 8, color: '#b00000' }}>Error: {errorMsg}</div>}
          </div>
        </section>
      </main>
    </div>
  )
}


