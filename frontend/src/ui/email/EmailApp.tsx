import React, { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export const EmailApp: React.FC = () => {
  const [clientName, setClientName] = useState('')
  const [articleUrl, setArticleUrl] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<string>('')
  const [error, setError] = useState<string>('')

  const onSubmit = async () => {
    setError(''); setResult('')
    if (!clientName.trim() || !articleUrl.trim()) { setError('Please enter client and URL'); return }
    setLoading(true)
    try {
      const res = await fetch('/api/v1/email/summarize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ client_name: clientName.trim(), article_url: articleUrl.trim() })
      })
      let j: any = null
      try { j = await res.json() } catch {
        const txt = await res.text()
        throw new Error(txt?.slice(0, 200) || 'Non-JSON error')
      }
      if (!res.ok) throw new Error(j?.detail || 'Failed to summarize')
      if (j?.markdown) {
        setResult(String(j.markdown))
      } else if (j?.status === 'accepted') {
        setResult('Request accepted. This is a placeholder; processing will return Markdown soon.')
      } else {
        setResult('No content returned.')
      }
    } catch (e:any) {
      setError(e.message || 'Error')
    } finally {
      setLoading(false)
    }
  }

  const onCopy = async () => {
    try { await navigator.clipboard.writeText(result) } catch {}
  }

  return (
    <div style={{ padding: 24 }}>
      <h2 style={{ marginTop: 0 }}>PR Coverage Email</h2>
      <div style={{ border: '1px solid #9e9e9e', padding: 16, display: 'grid', gap: 8 }}>
        <input value={clientName} onChange={e=>setClientName(e.target.value)} placeholder="Client name" style={{ border: '1px solid #000', padding: '6px 8px' }} />
        <input value={articleUrl} onChange={e=>setArticleUrl(e.target.value)} placeholder="Article URL" style={{ border: '1px solid #000', padding: '6px 8px' }} />
        <button onClick={onSubmit} disabled={loading} style={{ border: '1px solid #000', background: '#fff', padding: '6px 10px' }}>{loading ? 'Processing…' : 'Generate'}</button>
        {error && <div style={{ color: '#b00000' }}>{error}</div>}
      </div>
      {result && (
        <div style={{ marginTop: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h3 style={{ margin: 0 }}>Generated Email</h3>
            <button onClick={onCopy} style={{ border: '1px solid #000', background: '#fff', padding: '4px 8px' }}>Copy</button>
          </div>
          <div style={{ border: '1px solid #9e9e9e', padding: 12 }}>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{result}</ReactMarkdown>
          </div>
        </div>
      )}
    </div>
  )
}

