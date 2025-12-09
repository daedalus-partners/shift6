import React, { useEffect, useMemo, useState } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'

interface HitItem {
  id: string
  client_name?: string
  url?: string
  domain?: string
  title?: string
  snippet?: string
  match_type?: string
  confidence?: number | null
  published_at?: string | null
  created_at?: string | null
  is_read?: boolean
}

async function fetchHits(params: { new_only?: boolean; client?: string; start?: string; end?: string; page?: number; limit?: number } = {}) {
  const q = new URLSearchParams()
  if (params.new_only) q.set('new_only', 'true')
  if (params.client) q.set('client', params.client)
  if (params.start) q.set('start', params.start)
  if (params.end) q.set('end', params.end)
  if (params.page) q.set('page', String(params.page))
  if (params.limit) q.set('limit', String(params.limit))
  const r = await fetch(`${API_BASE}/coverage?${q.toString()}`)
  if (!r.ok) throw new Error('Failed to load coverage')
  return (await r.json()) as { items: HitItem[]; page: number; limit: number; count: number }
}

async function copyMarkdown(id: string) {
  const r = await fetch(`${API_BASE}/coverage/${id}/markdown`)
  if (!r.ok) return false
  const j = await r.json()
  await navigator.clipboard.writeText(j.markdown || '')
  return true
}

async function markAllRead() {
  const r = await fetch(`${API_BASE}/coverage/mark-all-read`, { method: 'POST' })
  return r.ok
}

async function importFromSheets() {
  const r = await fetch(`${API_BASE}/coverage/sheets/import`, { method: 'POST' })
  if (!r.ok) throw new Error('Sheets import failed')
  return await r.json()
}

async function runScan(limit = 20) {
  const r = await fetch(`${API_BASE}/coverage/scan?limit=${limit}`, { method: 'POST' })
  if (!r.ok) throw new Error('Scan failed')
  return await r.json()
}

export const CoverageApp: React.FC = () => {
  const [hits, setHits] = useState<HitItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [newOnly, setNewOnly] = useState(true)
  const [client, setClient] = useState('')
  const [dateStart, setDateStart] = useState('')
  const [dateEnd, setDateEnd] = useState('')
  const [page, setPage] = useState(1)
  const [limit, setLimit] = useState(20)
  const [serverCount, setServerCount] = useState(0)
  const [pasteOpen, setPasteOpen] = useState(false)
  const [pasteText, setPasteText] = useState('')
  const [pasteMode, setPasteMode] = useState<'csv' | 'lines'>('lines')
  const [pasteClient, setPasteClient] = useState('')
  const [activeTab, setActiveTab] = useState<'hits' | 'quotes'>('hits')

  type QuoteRow = {
    id: string
    client_name: string
    quote_text: string
    state?: string
    added_at?: string | null
    first_hit_at?: string | null
    last_hit_at?: string | null
    last_checked_at?: string | null
    next_run_at?: string | null
    hit_count?: number
    days_without_hit?: number
  }
  const [quotes, setQuotes] = useState<QuoteRow[]>([])
  const [quotesPage, setQuotesPage] = useState(1)
  const [quotesLimit, setQuotesLimit] = useState(20)
  const [quotesCount, setQuotesCount] = useState(0)

  const clients = useMemo(() => {
    const set = new Set<string>()
    hits.forEach((h) => h.client_name && set.add(h.client_name))
    return Array.from(set).sort()
  }, [hits])

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const res = await fetchHits({ new_only: newOnly, client: client || undefined, start: dateStart || undefined, end: dateEnd || undefined, page, limit })
      setHits(res.items)
      setServerCount(res.count)
    } catch (e: any) {
      setError(e?.message || 'Failed to load')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function loadQuotes() {
    setLoading(true)
    setError(null)
    try {
      const q = new URLSearchParams()
      if (client) q.set('client', client)
      q.set('page', String(quotesPage))
      q.set('limit', String(quotesLimit))
      const r = await fetch(`${API_BASE}/coverage/quotes?${q.toString()}`)
      if (!r.ok) throw new Error('Failed to load quotes')
      const j = await r.json()
      setQuotes(j.items || [])
      setQuotesCount(j.count || 0)
    } catch (e: any) {
      setError(e?.message || 'Failed to load quotes')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (activeTab === 'quotes') {
      loadQuotes()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab])

  async function deleteQuote(id: string) {
    try {
      setLoading(true)
      setError(null)
      const r = await fetch(`${API_BASE}/coverage/quotes/${id}`, { method: 'DELETE' })
      if (!r.ok) throw new Error('Delete failed')
      await loadQuotes()
    } catch (e: any) {
      setError(e?.message || 'Delete failed')
    } finally {
      setLoading(false)
    }
  }

  function parsePaste(): { items: { client_name: string; quote_text: string }[] } {
    const items: { client_name: string; quote_text: string }[] = []
    const text = pasteText.trim()
    if (!text) return { items }
    if (pasteMode === 'csv') {
      // Expecting headers: client,quote (flexible header names)
      const lines = text.split(/\r?\n/)
      if (!lines.length) return { items }
      const header = lines[0].split(',').map((h) => h.trim().toLowerCase())
      const ci = header.findIndex((h) => h.includes('client'))
      const qi = header.findIndex((h) => h.includes('quote'))
      for (let i = 1; i < lines.length; i++) {
        const cols = lines[i].split(',')
        const client = (cols[ci] || '').trim()
        const quote = (cols[qi] || '').trim()
        if (client && quote) items.push({ client_name: client, quote_text: quote })
      }
    } else {
      // One quote per line, assign selected client
      const client = pasteClient.trim()
      if (!client) return { items }
      for (const line of text.split(/\r?\n/)) {
        const quote = line.trim()
        if (quote) items.push({ client_name: client, quote_text: quote })
      }
    }
    return { items }
  }

  async function submitPaste() {
    try {
      setLoading(true)
      setError(null)
      const body = parsePaste()
      if (!body.items.length) throw new Error('No items parsed')
      const r = await fetch(`${API_BASE}/coverage/ingest/paste`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      if (!r.ok) throw new Error('Paste import failed')
      const result = await r.json()
      setPasteText('')
      setPasteClient('')
      setPasteOpen(false)
      // Switch to quotes tab and refresh to show newly added quotes
      setActiveTab('quotes')
      await loadQuotes()
      alert(`Added ${result.inserted || 0} quote(s)`)
    } catch (e: any) {
      setError(e?.message || 'Paste import failed')
    } finally {
      setLoading(false)
    }
  }

  async function insertSampleQuotes() {
    try {
      setLoading(true)
      setError(null)
      const body = {
        items: [
          { client_name: 'Acme', quote_text: 'We’re expanding to Europe.' },
          { client_name: 'Acme', quote_text: 'Security is our top priority.' },
          { client_name: 'Acme', quote_text: 'We raised a $10M Series A to accelerate product development.' },
        ],
      }
      const r = await fetch(`${API_BASE}/coverage/ingest/paste`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      if (!r.ok) throw new Error('Failed to insert samples')
      await r.json()
      await load()
      setPasteOpen(false)
    } catch (e: any) {
      setError(e?.message || 'Failed to insert samples')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ padding: 24 }}>
      <h2 style={{ marginTop: 0 }}>Coverage Tracker</h2>
      <div style={{ display: 'flex', gap: 12, marginBottom: 12 }}>
        <button 
          onClick={() => { setActiveTab('hits'); load(); }} 
          style={{ fontWeight: activeTab === 'hits' ? 'bold' : 'normal' }}
        >
          Hits
        </button>
        <button 
          onClick={() => { setActiveTab('quotes'); loadQuotes(); }} 
          style={{ fontWeight: activeTab === 'quotes' ? 'bold' : 'normal' }}
        >
          Quotes
        </button>
      </div>

      {activeTab === 'hits' && (
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 12, flexWrap: 'wrap' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <input type="checkbox" checked={newOnly} onChange={(e) => setNewOnly(e.target.checked)} /> New only
          </label>
          <select value={client} onChange={(e) => setClient(e.target.value)}>
            <option value="">All clients</option>
            {clients.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
          <input type="date" value={dateStart} onChange={(e) => setDateStart(e.target.value)} />
          <input type="date" value={dateEnd} onChange={(e) => setDateEnd(e.target.value)} />
          <button onClick={() => { setPage(1); load() }} disabled={loading}>Apply</button>
          <button onClick={async () => { if (await markAllRead()) load() }} disabled={loading}>Mark all read</button>
          <button onClick={() => setPasteOpen((v) => !v)} disabled={loading}>{pasteOpen ? 'Close paste' : 'Paste import'}</button>
          <button onClick={insertSampleQuotes} disabled={loading}>Insert sample quotes</button>
          <button onClick={async () => { try { setLoading(true); setError(null); await runScan(limit); await load() } catch (e: any) { setError(e?.message || 'Scan failed') } finally { setLoading(false) } }} disabled={loading}>Scan now</button>
          <select value={limit} onChange={(e) => { setLimit(parseInt(e.target.value || '20')); setPage(1) }}>
            <option value={10}>10</option>
            <option value={20}>20</option>
            <option value={50}>50</option>
            <option value={100}>100</option>
          </select>
        </div>
      )}

      {activeTab === 'hits' && pasteOpen && (
        <div style={{ border: '1px solid #e0e0e0', padding: 12, marginBottom: 12 }}>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 8, flexWrap: 'wrap' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <input type="radio" checked={pasteMode === 'lines'} onChange={() => setPasteMode('lines')} /> One quote per line
            </label>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <input type="radio" checked={pasteMode === 'csv'} onChange={() => setPasteMode('csv')} /> CSV (client, quote)
            </label>
            {pasteMode === 'lines' && (
              <input placeholder="Client name" value={pasteClient} onChange={(e) => setPasteClient(e.target.value)} />
            )}
            <button onClick={submitPaste} disabled={loading}>Import</button>
          </div>
          <textarea
            placeholder={pasteMode === 'csv' ? 'client,quote\nAcme,We are expanding...' : 'Paste one quote per line'}
            value={pasteText}
            onChange={(e) => setPasteText(e.target.value)}
            style={{ width: '100%', minHeight: 120 }}
          />
        </div>
      )}

      {loading && <div>Loading…</div>}
      {error && <div style={{ color: 'red' }}>{error}</div>}

      {activeTab === 'hits' && hits.length === 0 && !loading ? (
        <div style={{ border: '1px dashed #9e9e9e', padding: 24, color: '#555' }}>
          <div style={{ marginBottom: 12 }}>No coverage yet. Paste quotes to start scanning, or add sample quotes.</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button onClick={() => setPasteOpen(true)} disabled={loading}>Open paste import</button>
            <button onClick={insertSampleQuotes} disabled={loading}>Insert sample quotes</button>
          </div>
        </div>
      ) : activeTab === 'hits' ? (
        <div>
          {hits.map((h) => (
            <div key={h.id} style={{ borderBottom: '1px solid #e0e0e0', padding: '10px 4px', display: 'grid', gridTemplateColumns: 'minmax(220px, 1fr) 120px 140px 110px', gap: 12, alignItems: 'center' }}>
              <div>
                {!h.is_read && <span title="New" style={{ color: '#d32f2f', marginRight: 6 }}>!</span>}
                <a href={`${API_BASE}/coverage/r/${h.id}`} target="_blank" rel="noreferrer" style={{ color: '#000', textDecoration: 'none' }}>{h.title || h.url}</a>
                <div style={{ color: '#555', fontSize: 12 }}>{h.domain} — {h.client_name}</div>
              </div>
              <div>
                <span style={{ fontSize: 12, border: '1px solid #9e9e9e', padding: '2px 6px', borderRadius: 100 }}>{h.match_type}</span>
              </div>
              <div style={{ fontSize: 12, color: '#555' }}>{h.published_at ? new Date(h.published_at).toLocaleString() : (h.created_at ? new Date(h.created_at).toLocaleString() : '')}</div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button onClick={async () => { await copyMarkdown(h.id) }}>Copy Markdown</button>
                <button onClick={() => window.open(`${API_BASE}/coverage/r/${h.id}`, '_blank')}>Open</button>
              </div>
            </div>
          ))}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 12 }}>
            <button onClick={() => { if (page > 1) { setPage(page - 1); load() } }} disabled={loading || page <= 1}>Prev</button>
            <div style={{ fontSize: 12, color: '#555' }}>Page {page} • Showing {hits.length} items</div>
            <button onClick={() => { setPage(page + 1); load() }} disabled={loading || hits.length < limit}>Next</button>
          </div>
        </div>
      ) : null}

      {activeTab === 'quotes' && (
        <div>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 12, flexWrap: 'wrap' }}>
            <button onClick={() => setPasteOpen((v) => !v)} disabled={loading}>{pasteOpen ? 'Close' : '+ Add Quotes'}</button>
            <button onClick={() => loadQuotes()} disabled={loading}>Refresh</button>
          </div>

          {pasteOpen && (
            <div style={{ border: '1px solid #e0e0e0', padding: 12, marginBottom: 12 }}>
              <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 8, flexWrap: 'wrap' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <input type="radio" checked={pasteMode === 'lines'} onChange={() => setPasteMode('lines')} /> One quote per line
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <input type="radio" checked={pasteMode === 'csv'} onChange={() => setPasteMode('csv')} /> CSV (client, quote)
                </label>
                {pasteMode === 'lines' && (
                  <input placeholder="Client name" value={pasteClient} onChange={(e) => setPasteClient(e.target.value)} style={{ padding: '4px 8px' }} />
                )}
                <button onClick={submitPaste} disabled={loading}>Import</button>
              </div>
              <textarea
                placeholder={pasteMode === 'csv' ? 'client,quote\nAcme,We are expanding...' : 'Paste one quote per line'}
                value={pasteText}
                onChange={(e) => setPasteText(e.target.value)}
                style={{ width: '100%', minHeight: 120 }}
              />
            </div>
          )}

          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(220px, 1fr) 90px 140px 110px', gap: 12, padding: '8px 4px', borderBottom: '1px solid #e0e0e0', fontWeight: 600 }}>
            <div>Quote</div>
            <div>Client</div>
            <div>Added</div>
            <div>Actions</div>
          </div>
          {quotes.map((q) => (
            <div key={q.id} style={{ borderBottom: '1px solid #e0e0e0', padding: '10px 4px', display: 'grid', gridTemplateColumns: 'minmax(220px, 1fr) 90px 140px 110px', gap: 12, alignItems: 'center' }}>
              <div style={{ fontSize: 14 }}>{q.quote_text}</div>
              <div style={{ fontSize: 12, color: '#555' }}>{q.client_name}</div>
              <div style={{ fontSize: 12, color: '#555' }}>{q.added_at ? new Date(q.added_at).toLocaleDateString() : ''}</div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button onClick={() => deleteQuote(q.id)} disabled={loading}>Delete</button>
              </div>
            </div>
          ))}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 12 }}>
            <button onClick={() => { if (quotesPage > 1) { setQuotesPage(quotesPage - 1); loadQuotes() } }} disabled={loading || quotesPage <= 1}>Prev</button>
            <div style={{ fontSize: 12, color: '#555' }}>Page {quotesPage} • Showing {quotes.length} items</div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <select value={quotesLimit} onChange={(e) => { setQuotesLimit(parseInt(e.target.value || '20')); setQuotesPage(1); loadQuotes() }}>
                <option value={10}>10</option>
                <option value={20}>20</option>
                <option value={50}>50</option>
                <option value={100}>100</option>
              </select>
              <button onClick={() => { setQuotesPage(quotesPage + 1); loadQuotes() }} disabled={loading || quotes.length < quotesLimit}>Next</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}


