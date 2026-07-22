import React, { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const splitSubjectLine = (markdown: string, fallbackSubject?: string) => {
  const match = markdown.match(/^Subject:\s*([^\r\n]+)\r?\n(?:\r?\n)?/i)
  return {
    subject: String(fallbackSubject || match?.[1] || 'Coverage Live: Publication'),
    body: match ? markdown.slice(match[0].length) : markdown,
  }
}

const fallbackCopy = (text: string) => {
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', '')
  textarea.style.position = 'fixed'
  textarea.style.top = '0'
  textarea.style.left = '0'
  textarea.style.width = '2px'
  textarea.style.height = '2px'
  textarea.style.padding = '0'
  textarea.style.border = '0'
  textarea.style.outline = '0'
  textarea.style.background = 'transparent'
  document.body.appendChild(textarea)
  textarea.focus()
  textarea.select()
  textarea.setSelectionRange(0, text.length)
  const copied = document.execCommand('copy')
  document.body.removeChild(textarea)
  return copied
}

const copyText = async (text: string) => {
  try {
    if (!navigator.clipboard?.writeText) throw new Error('Clipboard API unavailable')
    await Promise.race([
      navigator.clipboard.writeText(text),
      new Promise((_, reject) => window.setTimeout(() => reject(new Error('Clipboard timed out')), 1500)),
    ])
    return
  } catch {
    if (!fallbackCopy(text)) throw new Error('Copy failed')
  }
}

export const EmailApp: React.FC = () => {
  const [clientName, setClientName] = useState('')
  const [articleUrl, setArticleUrl] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<string>('')
  const [subject, setSubject] = useState<string>('')
  const [copyStatus, setCopyStatus] = useState<string>('')
  const [error, setError] = useState<string>('')
  const [history, setHistory] = useState<Array<{id:number; url:string; title?:string; domain?:string; created_at?:string; summary_id?:number|null}>>([])
  const [search, setSearch] = useState('')

  const loadHistory = async () => {
    const client = clientName.trim()
    if (!client) { setHistory([]); return }
    try {
      const resp = await fetch(`/api/v1/email/history?client_name=${encodeURIComponent(client)}`)
      if (!resp.ok) return
      const j = await resp.json()
      setHistory(Array.isArray(j.items) ? j.items : [])
    } catch {}
  }

  useEffect(() => {
    const timer = window.setTimeout(() => { void loadHistory() }, 250)
    return () => window.clearTimeout(timer)
  }, [clientName])

  const onSubmit = async () => {
    setError(''); setResult(''); setSubject(''); setCopyStatus('')
    if (!clientName.trim() || !articleUrl.trim()) { setError('Please enter client and URL'); return }
    setLoading(true)
    try {
      const res = await fetch('/api/v1/email/summarize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() },
        body: JSON.stringify({ client_name: clientName.trim(), article_url: articleUrl.trim() })
      })
      let j: any = null
      const txt = await res.text()
      try { j = JSON.parse(txt) } catch {
        throw new Error(txt?.slice(0, 200) || 'Non-JSON error')
      }
      if (!res.ok) throw new Error(j?.detail || 'Failed to summarize')
      if (j?.markdown) {
        const email = splitSubjectLine(String(j.body_markdown ?? j.markdown), j.subject)
        setResult(email.body)
        setSubject(email.subject)
      } else if (j?.status === 'accepted') {
        setResult('Request accepted. This is a placeholder; processing will return Markdown soon.')
      } else {
        setResult('No content returned.')
      }
      void loadHistory()
    } catch (e:any) {
      setError(e.message || 'Error')
    } finally {
      setLoading(false)
    }
  }

  const onCopy = async () => {
    const prefix = subject ? `Subject: ${subject}\n\n` : ''
    setCopyStatus('Copying…')
    try {
      await copyText(`${prefix}${result}`)
      setCopyStatus('Copied')
      window.setTimeout(() => setCopyStatus(''), 2500)
    } catch {
      setCopyStatus('Copy failed — select the email and copy manually')
    }
  }

  const openSummary = async (summaryId?: number|null) => {
    if (!summaryId) return
    try {
      const client = clientName.trim()
      if (!client) return
      const r = await fetch(`/api/v1/email/summary/${summaryId}?client_name=${encodeURIComponent(client)}`)
      const j = await r.json()
      if (r.ok && j?.markdown) {
        const email = splitSubjectLine(String(j.body_markdown ?? j.markdown), j.subject)
        setResult(email.body)
        setSubject(email.subject)
      }
    } catch {}
  }

  const onSearch = async () => {
    const q = search.trim()
    if (!q) { void loadHistory(); return }
    const client = clientName.trim()
    if (!client) { setError('Enter a client name before searching history'); return }
    try {
      const r = await fetch(`/api/v1/email/history/search?q=${encodeURIComponent(q)}&client_name=${encodeURIComponent(client)}`)
      const j = await r.json()
      if (r.ok && Array.isArray(j.items)) {
        setHistory(j.items)
      }
    } catch {}
  }

  return (
    <div style={{ padding: 24 }}>
      <h2 style={{ marginTop: 0 }}>PR Coverage Email</h2>
      <div style={{ border: '1px solid #9e9e9e', padding: 16, display: 'grid', gap: 8 }}>
        <input value={clientName} onChange={e=>setClientName(e.target.value)} placeholder="Client name" style={{ border: '2px solid #000', padding: '6px 8px' }} />
        <input value={articleUrl} onChange={e=>setArticleUrl(e.target.value)} placeholder="Article URL" style={{ border: '2px solid #000', padding: '6px 8px' }} />
        <button onClick={onSubmit} disabled={loading} style={{ border: '2px solid #000', background: '#fff', padding: '6px 10px' }}>{loading ? 'Processing…' : 'Generate'}</button>
        {error && <div style={{ color: '#b00000' }}>{error}</div>}
      </div>
      {result && (
        <div style={{ marginTop: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h3 style={{ margin: 0 }}>Generated Email</h3>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              {copyStatus && <span role="status" aria-live="polite" style={{ fontSize: 13 }}>{copyStatus}</span>}
              <button onClick={onCopy} disabled={copyStatus === 'Copying…'} style={{ border: '2px solid #000', background: '#fff', padding: '4px 8px' }}>Copy subject + email</button>
            </div>
          </div>
          <div style={{ border: '1px solid #9e9e9e', padding: 12 }}>
            <div style={{ marginBottom: 12 }}><strong>Subject:</strong> {subject}</div>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{result}</ReactMarkdown>
          </div>
        </div>
      )}
      <section style={{ marginTop: 24 }}>
        <h3 style={{ margin: 0 }}>History</h3>
        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          <input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search coverage…" style={{ border: '2px solid #000', padding: '6px 8px', flex: 1 }} />
          <button onClick={onSearch} style={{ border: '2px solid #000', background: '#fff', padding: '6px 8px' }}>Search</button>
        </div>
        <ul style={{ listStyle: 'none', padding: 0, marginTop: 8 }}>
          {history.map(item => (
            <li key={item.summary_id || item.id} style={{ display: 'flex', gap: 8, alignItems: 'center', borderTop: '1px solid #9e9e9e', padding: '6px 0' }}>
              <button onClick={()=>openSummary(item.summary_id || undefined)} style={{ border: '2px solid #000', background: '#fff', padding: '2px 6px' }}>Open</button>
              <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.title || item.url}</span>
              <span style={{ color: '#555', fontSize: 12 }}>{item.domain}</span>
              <span style={{ color: '#777', fontSize: 12 }}>{item.created_at?.slice(0, 19).replace('T',' ')}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}
