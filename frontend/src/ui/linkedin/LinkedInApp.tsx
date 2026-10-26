import React, { useEffect, useRef, useState } from 'react'
import { button, control, ClientLinkedInProfile, Contact, jsonRequest } from './ClientLinkedInProfile'

type Client = { id: number; name: string }
type Draft = { content: string; mentions: (Contact & { reason: string })[]; checks: string[] }
export function LinkedInApp() {
  const [clients, setClients] = useState<Client[]>([])
  const [clientId, setClientId] = useState(0)
  const [coverage, setCoverage] = useState('')
  const [url, setUrl] = useState('')
  const [publication, setPublication] = useState('')
  const [journalist, setJournalist] = useState('')
  const [angle, setAngle] = useState('')
  const [length, setLength] = useState('Standard')
  const [draft, setDraft] = useState<Draft | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const generation = useRef(0)
  useEffect(() => {
    let active = true
    jsonRequest('/clients/').then(data => { if (active) { setClients(data); setClientId(data[0]?.id || 0) } }).catch(e => { if (active) setMessage(e.message) })
    return () => { active = false }
  }, [])
  useEffect(() => () => { generation.current++ }, [])
  const changeClient = (id: number) => {
    generation.current++; setClientId(id); setDraft(null); setCoverage(''); setUrl(''); setPublication(''); setJournalist(''); setAngle(''); setMessage(''); setBusy(false)
  }
  const generate = async (e: React.FormEvent) => {
    e.preventDefault()
    const request = ++generation.current
    setBusy(true); setMessage(''); setDraft(null)
    try {
      const data = await jsonRequest(`/api/v1/linkedin/${clientId}/generate`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ coverage, url, publication, journalist, angle, length }) })
      if (request === generation.current) setDraft(data)
    } catch (e: any) { if (request === generation.current) setMessage(e.message) }
    finally { if (request === generation.current) setBusy(false) }
  }
  const copy = async () => {
    try { await navigator.clipboard.writeText(draft!.content); setMessage('Post copied. Activate the suggested tags in LinkedIn before publishing.') }
    catch { setMessage('Copy unavailable. Select and copy the post text below.') }
  }
  return <main style={{ maxWidth: 1100, margin: '0 auto', padding: 24, color: '#111' }}>
    <h1>LinkedIn Announcer</h1>
    <p>Turn media coverage into a post in your client’s voice.</p>
    <label>Client <select style={{ ...control, width: 'auto', minWidth: 200 }} value={clientId} onChange={e => changeClient(Number(e.target.value))} disabled={!clients.length}>{!clients.length && <option value={0}>No clients available</option>}{clients.map(c => <option value={c.id} key={c.id}>{c.name}</option>)}</select></label>
    {!clients.length && <p>Add a client in <a href="/quotes">Quote Generator</a> to get started.</p>}
    {!!clientId && <ClientLinkedInProfile key={clientId} clientId={clientId} />}
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 380px), 1fr))', gap: 24, marginTop: 24 }}>
      <form onSubmit={generate}>
        <label style={{ display: 'block' }}>Coverage text<textarea style={{ ...control, marginTop: 8 }} rows={14} required minLength={80} maxLength={60000} value={coverage} onChange={e => setCoverage(e.target.value)} placeholder="Paste the article or coverage excerpt, including the headline and byline where available. A URL alone is not enough." /></label>
        <p style={{ fontSize: 13 }}>Only the supplied coverage is used as evidence for the announcement. Check the draft against the original before publishing.</p>
        {([
          ['Article URL (optional)', url, setUrl, 'url', 2048],
          ['Publication (optional)', publication, setPublication, 'text', 256],
          ['Journalist (optional)', journalist, setJournalist, 'text', 256],
          ['Focus or angle (optional)', angle, setAngle, 'text', 2000],
        ] as const).map(([label, value, setter, type, maxLength]) => <label key={label} style={{ display: 'block', margin: '14px 0' }}>{label}<input style={control} type={type} maxLength={maxLength} value={value} onChange={e => setter(e.target.value)} /></label>)}
        <label>Post length<select style={{ ...control, marginBottom: 16 }} value={length} onChange={e => setLength(e.target.value)}><option>Standard</option><option>Short</option></select></label>
        <button style={{ ...button, background: '#111', color: '#fff' }} disabled={!clientId || busy || coverage.trim().length < 80}>{busy ? 'Writing post…' : draft ? 'Generate another draft' : 'Generate post'}</button>
      </form>
      <section aria-label="Generated LinkedIn post" style={{ border: '1px solid #aaa', borderRadius: 6, padding: 20, alignSelf: 'start' }}>
        <h2 style={{ marginTop: 0 }}>Your post</h2>
        {!draft ? <p>{busy ? 'Preparing your announcement…' : 'Your editable draft and suggested tags will appear here.'}</p> : <>
          <label>Edit post<textarea style={{ ...control, marginTop: 8 }} rows={17} value={draft.content} onChange={e => setDraft({ ...draft, content: e.target.value })} /></label>
          <p style={{ color: draft.content.length > 3000 ? '#b00000' : '#555' }}>{draft.content.length.toLocaleString()} / 3,000 characters</p>
          <button style={button} type="button" disabled={!draft.content.trim() || draft.content.length > 3000} onClick={copy}>Copy post</button>
          <h3>Suggested tags</h3>
          <p>Copying a name does not create a live tag. In LinkedIn, type @ and select the matching account. Check these saved profiles first.</p>
          {draft.mentions.length ? <ul>{draft.mentions.map(m => <li key={m.url} style={{ marginBottom: 10 }}><a href={m.url} target="_blank" rel="noreferrer">{m.name}</a> · {m.role}<div style={{ fontSize: 13 }}>{m.reason}</div></li>)}</ul> : <p>No confirmed saved contacts matched. Verify the journalist or publication’s profile, then save it in the client profile for next time.</p>}
          <h3>Before publishing</h3><ul>{draft.checks.map(check => <li key={check}>{check}</li>)}</ul>
        </>}
        <p role="status" aria-live="polite">{message}</p>
      </section>
    </div>
    <details style={{ marginTop: 24 }}><summary>What makes a useful coverage announcement?</summary><p>Lead with the news, share one relevant takeaway, credit the journalist and publication, and give readers the article link. Use short paragraphs, relevant mentions and a few focused hashtags. A passing mention should not become a claim of endorsement.</p><p>Based on <a href="https://www.linkedin.com/business/talent/blog/talent-acquisition/how-to-write-engaging-post-in-linkedin-feed" target="_blank" rel="noreferrer">LinkedIn’s posting guidance</a> and <a href="https://www.linkedin.com/help/linkedin/answer/a525082/mention-people-in-your-posts" target="_blank" rel="noreferrer">mention instructions</a>.</p></details>
  </main>
}
