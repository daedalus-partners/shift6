import React, { useEffect, useState } from 'react'

export type Contact = { name: string; url: string; role: 'Journalist' | 'Publication' | 'Spokesperson' | 'Partner' }
type Profile = { page_url: string; voice: string; audience: string; context: string; examples: string; hashtags: string; contacts: Contact[] }
const blank: Profile = { page_url: '', voice: 'Clear, warm and factual. British English. Avoid hype.', audience: '', context: '', examples: '', hashtags: '', contacts: [] }
export const control: React.CSSProperties = { boxSizing: 'border-box', width: '100%', padding: 10, border: '1px solid #999', borderRadius: 4, font: 'inherit', background: '#fff', color: '#111' }
export const button: React.CSSProperties = { padding: '9px 16px', border: '1px solid #111', borderRadius: 4, background: '#fff', color: '#111', cursor: 'pointer', font: 'inherit' }
export async function jsonRequest(url: string, options?: RequestInit) {
  const response = await fetch(url, options)
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Please check the fields and try again.')
  return data
}

export function ClientLinkedInProfile({ clientId }: { clientId: number }) {
  const [profile, setProfile] = useState<Profile>(blank)
  const [ready, setReady] = useState(false)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  useEffect(() => {
    let active = true
    setReady(false)
    jsonRequest(`/api/v1/linkedin/${clientId}/profile`).then(data => { if (active) { setProfile(data); setReady(true) } }).catch(e => { if (active) setMessage(e.message) })
    return () => { active = false }
  }, [clientId])
  const set = (key: keyof Profile, value: unknown) => { setProfile(p => ({ ...p, [key]: value })); setMessage('Unsaved changes') }
  const save = async (e: React.FormEvent) => {
    e.preventDefault(); setSaving(true)
    try {
      await jsonRequest(`/api/v1/linkedin/${clientId}/profile`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(profile) })
      setMessage('Saved for this client in Quote Generator and LinkedIn Announcer.')
    } catch (e: any) { setMessage(e.message) } finally { setSaving(false) }
  }
  return <details style={{ border: '1px solid #aaa', padding: 16, margin: '16px 0', borderRadius: 6 }}>
    <summary style={{ cursor: 'pointer', fontWeight: 600 }}>Saved client LinkedIn profile</summary>
    <p>Uses your existing Quote Generator client. Save once and reuse for future announcements. Save changes before generating.</p>
    {!ready ? <p role="status">{message || 'Loading profile…'}</p> : <form onSubmit={save}>
      {([
        ['page_url', 'Company LinkedIn URL', 'https://www.linkedin.com/company/…'],
        ['voice', 'Voice and writing preferences', 'Tone, language, words to avoid…'],
        ['audience', 'Audience', 'Who should this coverage matter to?'],
        ['context', 'Approved public background', 'Company description, key messages and spokesperson details. Only include information approved for public use.'],
        ['examples', 'Approved example LinkedIn posts', 'Paste examples to capture this client’s voice.'],
        ['hashtags', 'Preferred hashtags (up to three per post)', '#ClimateTech #Innovation'],
      ] as const).map(([key, label, placeholder]) => <label key={key} style={{ display: 'block', margin: '14px 0' }}>{label}
        {key === 'page_url' || key === 'hashtags' ? <input style={control} type={key === 'page_url' ? 'url' : 'text'} maxLength={key === 'page_url' ? 512 : 256} value={profile[key]} onChange={e => set(key, e.target.value)} placeholder={placeholder} /> :
          <textarea style={control} rows={key === 'examples' ? 5 : 3} maxLength={{ voice: 4000, audience: 2000, context: 6000, examples: 12000 }[key]} value={profile[key]} onChange={e => set(key, e.target.value)} placeholder={placeholder} />}
      </label>)}
      <h3>Confirmed LinkedIn contacts</h3>
      <p>Save the exact account name and profile link. Relevant names found in coverage are suggested automatically. Confirm the correct account before saving.</p>
      {profile.contacts.map((contact, i) => <fieldset key={i} style={{ border: '1px solid #bbb', marginBottom: 12, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        <legend>Contact {i + 1}</legend>
        <label style={{ flex: '1 1 180px' }}>Exact account name<input style={control} required minLength={2} maxLength={128} value={contact.name} onChange={e => set('contacts', profile.contacts.map((c, n) => n === i ? { ...c, name: e.target.value } : c))} /></label>
        <label style={{ flex: '2 1 260px' }}>LinkedIn profile URL<input style={control} required type="url" maxLength={512} value={contact.url} onChange={e => set('contacts', profile.contacts.map((c, n) => n === i ? { ...c, url: e.target.value } : c))} /></label>
        <label>Role<select style={control} value={contact.role} onChange={e => set('contacts', profile.contacts.map((c, n) => n === i ? { ...c, role: e.target.value } : c))}>{['Journalist', 'Publication', 'Spokesperson', 'Partner'].map(r => <option key={r}>{r}</option>)}</select></label>
        <button style={button} type="button" onClick={() => set('contacts', profile.contacts.filter((_, n) => n !== i))}>Remove</button>
      </fieldset>)}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        <button type="button" style={button} disabled={profile.contacts.length >= 40} onClick={() => set('contacts', [...profile.contacts, { name: '', url: '', role: 'Spokesperson' }])}>Add contact</button>
        <button style={{ ...button, background: '#111', color: '#fff' }} disabled={saving}>{saving ? 'Saving…' : 'Save client profile'}</button>
      </div>
      <p role="status">{message}</p>
    </form>}
  </details>
}
