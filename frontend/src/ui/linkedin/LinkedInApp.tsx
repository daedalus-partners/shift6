import React, { useEffect, useRef, useState } from 'react'
import { button, control, ClientLinkedInProfile, Contact, jsonRequest } from './ClientLinkedInProfile'

type Client = { id: number; name: string; slug: string }
type Account = Contact & { status: string; reason: string; evidence_url: string }
type Discovery = { accounts: Account[]; posts: {url: string; title: string; status: string; reason: string; excerpt: string}[]; status: string; publication_search?: string; journalist_search?: string; post_search: string }
type Draft = { repost_content?: string; discovery?: Discovery; content: string; mentions: (Contact & { reason: string })[]; checks: string[]; source?: { title: string; publication: string; journalist?: string; attribution?: Record<string, {status: string; evidence: {source: string; names: string[]}[]}>; excerpt: string } }
export function LinkedInApp() {
  const [clients, setClients] = useState<Client[]>([])
  const [clientId, setClientId] = useState(0)
  const [clientsLoading, setClientsLoading] = useState(true)
  const [showAddClient, setShowAddClient] = useState(false)
  const [newClientName, setNewClientName] = useState('')
  const [addingClient, setAddingClient] = useState(false)
  const [clientError, setClientError] = useState('')
  const [coverage, setCoverage] = useState('')
  const [url, setUrl] = useState('')
  const [angle, setAngle] = useState('')
  const [length, setLength] = useState('Standard')
  const [includeHashtags, setIncludeHashtags] = useState(false)
  const [profileVersion, setProfileVersion] = useState(0)
  const [postMode, setPostMode] = useState<'article' | 'repost'>('article')
  const [draft, setDraft] = useState<Draft | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const generation = useRef(0)
  useEffect(() => {
    let active = true
    jsonRequest('/clients/').then(data => { if (active) { setClients(data); setClientId(data[0]?.id || 0) } }).catch(e => { if (active) setClientError(e.message) }).finally(() => { if (active) setClientsLoading(false) })
    return () => { active = false }
  }, [])
  useEffect(() => () => { generation.current++ }, [])
  const changeClient = (id: number) => {
    generation.current++; setClientId(id); setDraft(null); setCoverage(''); setUrl(''); setAngle(''); setMessage(''); setBusy(false)
  }
  const addClient = async (e: React.FormEvent) => {
    e.preventDefault()
    const name = newClientName.trim()
    if (!name || addingClient) return
    const existing = clients.find(c => c.name.trim().toLocaleLowerCase() === name.toLocaleLowerCase())
    if (existing) { changeClient(existing.id); setShowAddClient(false); setNewClientName(''); setClientError(''); return }
    const slug = name.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 64).replace(/^-+|-+$/g, '') || `client-${Date.now()}`
    setAddingClient(true); setClientError('')
    try {
      const response = await fetch('/clients/', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, slug }) })
      if (response.status === 409) {
        const updated: Client[] = await jsonRequest('/clients/')
        setClients(updated)
        const match = updated.find(c => c.name.trim().toLocaleLowerCase() === name.toLocaleLowerCase())
        if (!match) throw new Error('A client with a similar name already exists. Use a more specific name.')
        changeClient(match.id)
      } else {
        if (!response.ok) throw new Error('Could not add this client. Please try again.')
        const created: Client = await response.json()
        setClients(current => [...current, created].sort((a, b) => a.slug.localeCompare(b.slug)))
        changeClient(created.id)
      }
      setShowAddClient(false); setNewClientName('')
    } catch (e: any) { setClientError(e.message || 'Could not add this client.') }
    finally { setAddingClient(false) }
  }
  const generate = async (e: React.FormEvent) => {
    e.preventDefault()
    const request = ++generation.current
    setBusy(true); setMessage(''); setDraft(null); setPostMode('article')
    try {
      const data = await jsonRequest(`/api/v1/linkedin/${clientId}/generate`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ coverage, url, angle, length, include_hashtags: includeHashtags }) })
      if (request === generation.current) { setDraft(data); setProfileVersion(v => v + 1); if (data.discovery?.posts?.some((p: any) => p.status === 'article_link_matched')) setPostMode('repost') }
    } catch (e: any) { if (request === generation.current) setMessage(e.message) }
    finally { if (request === generation.current) setBusy(false) }
  }
  const copy = async () => {
    try { await navigator.clipboard.writeText(postMode === 'repost' ? draft!.repost_content || draft!.content : draft!.content); setMessage(postMode === 'repost' ? 'Commentary copied. Open the publisher’s post and choose Repost with your thoughts.' : 'Post copied. Select any account mentions in LinkedIn before publishing.') }
    catch { setMessage('Copy unavailable. Select and copy the post text below.') }
  }
  const displayedContent = draft ? (postMode === 'repost' ? draft.repost_content || draft.content : draft.content) : ''
  return <main style={{ maxWidth: 1100, margin: '0 auto', padding: 24, color: '#111' }}>
    <h1>LinkedIn Announcer</h1>
    <p>Paste a coverage link. We’ll read the article and write the LinkedIn post in your client’s voice.</p>
    <label>Client <select aria-label="Client" style={{ ...control, width: 'auto', minWidth: 200 }} value={clientId} onChange={e => { if (e.target.value === '__add__') { setShowAddClient(true); setClientError('') } else { changeClient(Number(e.target.value)); setShowAddClient(false) } }} disabled={clientsLoading || addingClient}>
      {!clients.length && <option value={0}>{clientsLoading ? 'Loading clients…' : 'Select or add a client'}</option>}
      {clients.map(c => <option value={c.id} key={c.id}>{c.name}</option>)}
      <option value="__add__">+ Add client…</option>
    </select></label>
    {showAddClient && <form aria-label="Add client" onSubmit={addClient} style={{border:'1px solid #aaa',borderRadius:6,padding:16,marginTop:16,maxWidth:500}}>
      <h2 style={{marginTop:0,fontSize:18}}>Add a client</h2>
      <p>The client will be available in both LinkedIn Announcer and Quote Generator.</p>
      <label>Client name<input autoFocus style={control} required maxLength={128} value={newClientName} onChange={e => setNewClientName(e.target.value)} placeholder="Company or client name" disabled={addingClient} /></label>
      <div style={{display:'flex',gap:10,marginTop:12}}><button style={{...button,background:'#111',color:'#fff'}} disabled={addingClient || !newClientName.trim()}>{addingClient ? 'Adding…' : 'Add client'}</button><button type="button" style={button} disabled={addingClient} onClick={() => {setShowAddClient(false);setNewClientName('');setClientError('')}}>Cancel</button></div>
    </form>}
    {clientError && <p role="alert" style={{color:'#b00000'}}>{clientError}</p>}
    {!!clientId && <ClientLinkedInProfile key={`${clientId}-${profileVersion}`} clientId={clientId} />}
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 380px), 1fr))', gap: 24, marginTop: 24 }}>
      <form onSubmit={generate}>
        <label style={{ display: 'block' }}>Article link<input style={{ ...control, marginTop: 8 }} type="url" maxLength={2048} required={!coverage.trim()} value={url} onChange={e => setUrl(e.target.value)} placeholder="https://publication.com/your-coverage" /></label>
        <p style={{ fontSize: 13 }}>We’ll read the coverage and write the post for you. No need to write a summary.</p>
        <details style={{ margin: '16px 0' }}><summary style={{ cursor: 'pointer' }}>Paste article text instead</summary>
          <p>For paywalled or blocked articles, paste the text here. This text will be used instead of reading the link.</p>
          <textarea aria-label="Article text fallback" style={control} rows={8} minLength={80} maxLength={60000} value={coverage} onChange={e => setCoverage(e.target.value)} placeholder="Paste the article text, including the headline and byline where available." />
        </details>
        <p style={{ fontSize: 13 }}>Publication and journalist are identified from the article. Missing or conflicting attribution is left uncredited.</p>
        {([
          ['Focus or angle (optional)', angle, setAngle, 'text', 2000],
        ] as const).map(([label, value, setter, type, maxLength]) => <label key={label} style={{ display: 'block', margin: '14px 0' }}>{label}<input style={control} type={type} maxLength={maxLength} value={value} onChange={e => setter(e.target.value)} /></label>)}
        <label>Post length<select style={{ ...control, marginBottom: 16 }} value={length} onChange={e => setLength(e.target.value)}><option>Standard</option><option>Short</option></select></label>
        <label style={{ display: 'flex', gap: 8, marginBottom: 16 }}><input type="checkbox" checked={includeHashtags} onChange={e => setIncludeHashtags(e.target.checked)} />Include hashtags (optional)</label>
        <button style={{ ...button, background: '#111', color: '#fff' }} disabled={!clientId || busy || (!url.trim() && coverage.trim().length < 80)}>{busy ? 'Reading coverage and writing…' : draft ? 'Generate another draft' : 'Generate post'}</button>
      </form>
      <section aria-label="Generated LinkedIn post" style={{ border: '1px solid #aaa', borderRadius: 6, padding: 20, alignSelf: 'start' }}>
        <h2 style={{ marginTop: 0 }}>Your post</h2>
        {!draft ? <p>{busy ? 'Reading the article and preparing your announcement…' : 'Your draft, account matches and sharing recommendation will appear here.'}</p> : <>
          {draft.discovery && <div style={{ background: '#f5f5f5', padding: 14, marginBottom: 16 }}>
            <strong>{draft.discovery.posts.length ? 'Publisher LinkedIn post found' : 'Share the article link'}</strong>
            <p>{draft.discovery.posts.length ? 'Check the original below. Repost with your thoughts to add this commentary above the publisher’s post, or publish your own post with the article link.' : draft.discovery.status === 'searched' ? 'No matching post from the publication was found in public search. Use the article link; LinkedIn search below can catch posts that are not indexed.' : 'Public LinkedIn search is temporarily unavailable. Your article-link post is ready; you can also check LinkedIn below.'}</p>
            {draft.discovery.posts.map(p => <p key={p.url}><a href={p.url} target="_blank" rel="noreferrer">Open publisher’s post ↗</a><br /><small>{p.reason}</small></p>)}
            <a href={draft.discovery.post_search} target="_blank" rel="noreferrer">Check for this story on LinkedIn ↗</a>
          </div>}
          {draft.discovery && draft.discovery.posts.length > 0 && <label style={{display:'block',marginBottom:12}}>How will you share it?<select style={control} value={postMode} onChange={e => setPostMode(e.target.value as 'article' | 'repost')}><option value="article">My own post + article link</option><option value="repost">Repost with my thoughts</option></select></label>}
          <label>{postMode === 'repost' ? 'Your repost commentary' : 'Edit post'}<textarea style={{ ...control, marginTop: 8 }} rows={17} value={postMode === 'repost' ? draft.repost_content || draft.content : draft.content} onChange={e => setDraft({ ...draft, [postMode === 'repost' ? 'repost_content' : 'content']: e.target.value })} /></label>
          <p style={{ color: displayedContent.length > 3000 ? '#b00000' : '#555' }}>{displayedContent.length.toLocaleString()} / 3,000 characters</p>
          <button style={button} type="button" disabled={!displayedContent.trim() || displayedContent.length > 3000} onClick={copy}>Copy post</button>
          {draft.source && <div style={{ marginTop: 16 }}><strong>Attribution from the source</strong><p>Publication: {draft.source.publication || "Not clearly identified — omitted"}<br />Journalist / byline: {draft.source.journalist || "Not clearly identified — omitted"}</p></div>}
          {draft.source && <details style={{ marginTop: 16 }}><summary>Coverage and attribution evidence</summary>{draft.source.attribution && Object.entries(draft.source.attribution).map(([key, value]) => <div key={key}><strong>{key}: {value.status.replaceAll("_", " ")}</strong><ul>{value.evidence.map((item, i) => <li key={i}>{item.source}: {item.names.join(", ")}</li>)}</ul></div>)}<p><strong>{draft.source.title}</strong>{draft.source.publication ? ` · ${draft.source.publication}` : ''}</p><p style={{ whiteSpace: 'pre-wrap', maxHeight: 240, overflowY: 'auto' }}>{draft.source.excerpt}</p></details>}
          <h3>People and publication</h3>
          <p>We find the accounts for this coverage. Open an account to check it; in LinkedIn, type @ and select that name to make the mention clickable.</p>
          {draft.discovery?.accounts.map(account => <div key={account.url} style={{borderTop:'1px solid #ddd',padding:'12px 0'}}><a href={account.url} target="_blank" rel="noreferrer"><strong>{account.name}</strong> ↗</a><div>{account.role} · {account.status === 'candidate' ? 'Possible match — check identity' : account.status === 'saved' ? 'Saved account' : 'Account matched and saved'}</div><small>{account.reason}</small></div>)}
          {draft.discovery && <div style={{marginTop:12}}>{draft.discovery.publication_search && <p><a href={draft.discovery.publication_search} target="_blank" rel="noreferrer">{draft.discovery.accounts.some(a => a.role === 'Publication') ? 'Other publication account results' : `Find ${draft.source?.publication || 'the publication'} on LinkedIn`} ↗</a></p>}{draft.discovery.journalist_search && <p><a href={draft.discovery.journalist_search} target="_blank" rel="noreferrer">{draft.discovery.accounts.some(a => a.role === 'Journalist') ? 'Other journalist account results' : `Find ${draft.source?.journalist || 'the journalist'} on LinkedIn`} ↗</a></p>}</div>}
          <h3>Before publishing</h3><ul>{draft.checks.map(check => <li key={check}>{check}</li>)}</ul>
        </>}
        <p role="status" aria-live="polite">{message}</p>
      </section>
    </div>
    <details style={{ marginTop: 24 }}><summary>What makes a useful coverage announcement?</summary><p>Lead with the news, share one relevant takeaway, credit the journalist and publication, and give readers the article link. Use short paragraphs and relevant mentions. Hashtags are optional. A passing mention should not become a claim of endorsement.</p><p>Based on <a href="https://www.linkedin.com/business/talent/blog/talent-acquisition/how-to-write-engaging-post-in-linkedin-feed" target="_blank" rel="noreferrer">LinkedIn’s posting guidance</a> and <a href="https://www.linkedin.com/help/linkedin/answer/a525082/mention-people-in-your-posts" target="_blank" rel="noreferrer">mention instructions</a>.</p></details>
  </main>
}
