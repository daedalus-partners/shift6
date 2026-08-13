import React, { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

type UnknownRecord = Record<string, unknown>
type DateBasis = 'published' | 'captured' | 'generated'
type RecordFilters = {
  clientName: string
  publication: string
  startDate: string
  endDate: string
  dateBasis: DateBasis
}

type PublicationDateDetails = {
  value: string | null
  source: string | null
  confidence: string | null
  status: string | null
}

type ScoreDetails = {
  value: string | number | null
  status: string | null
  methodologyVersion: string | null
}

type EvidenceDetails = {
  status: string | null
  screenshotUrl: string | null
  thumbnailUrl: string | null
  capturedAt: string | null
}

type CoverageDetails = {
  publicationDate: PublicationDateDetails
  score: ScoreDetails
  evidence: EvidenceDetails
}

type CoverageRecord = CoverageDetails & {
  id: string | number
  clientName: string | null
  title: string | null
  url: string | null
  publication: string | null
  generatedAt: string | null
}

type HistoryItem = {
  id: number
  url: string
  title?: string
  domain?: string
  created_at?: string
  summary_id?: number | null
}

const controlStyle: React.CSSProperties = {
  border: '2px solid #000',
  background: '#fff',
  color: '#000',
  padding: '6px 8px',
  minHeight: 34,
  boxSizing: 'border-box',
}

const mutedStyle: React.CSSProperties = { color: '#666', fontSize: 12 }

const isObject = (value: unknown): value is UnknownRecord => (
  typeof value === 'object' && value !== null && !Array.isArray(value)
)

const firstPresent = (...values: unknown[]) => {
  for (const value of values) {
    if (value !== null && value !== undefined && value !== '') return value
  }
  return null
}

const asText = (value: unknown) => {
  const present = firstPresent(value)
  return typeof present === 'string' || typeof present === 'number' ? String(present) : null
}

const humanize = (value: string | null) => {
  if (!value) return null
  return value.replaceAll('_', ' ').replaceAll('-', ' ').replace(/\b\w/g, letter => letter.toUpperCase())
}

const pendingOrUnavailable = (status: string | null) => (
  ['pending', 'queued', 'partial', 'unscorable', 'awaiting'].some(marker => status?.toLowerCase().includes(marker))
    ? 'Pending'
    : 'Unavailable'
)

const formatDate = (value: string | null, includeTime = false) => {
  if (!value) return null
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return new Intl.DateTimeFormat(undefined, includeTime
    ? { dateStyle: 'medium', timeStyle: 'short' }
    : { dateStyle: 'medium' }
  ).format(parsed)
}

const findScreenshotEvidence = (value: unknown): UnknownRecord | null => {
  if (isObject(value)) return value
  if (!Array.isArray(value)) return null
  const screenshot = value.find(item => isObject(item) && String(item.kind || '').toLowerCase().includes('screenshot'))
  return isObject(screenshot) ? screenshot : (isObject(value[0]) ? value[0] : null)
}

const normalizeCoverageDetails = (payload: unknown): CoverageDetails => {
  const root = isObject(payload) ? payload : {}
  const publicationValue = root.publication_date
  const publication = isObject(publicationValue) ? publicationValue : {}
  const scoreValue = isObject(root.score) ? root.score : root.shift6_score
  const score = isObject(scoreValue) ? scoreValue : {}
  const primitiveScore = typeof scoreValue === 'string' || typeof scoreValue === 'number'
    ? scoreValue
    : null
  const selectedScreenshot = isObject(root.screenshot) ? root.screenshot : null
  const selectedThumbnail = isObject(root.thumbnail) ? root.thumbnail : null
  const evidence = selectedScreenshot || findScreenshotEvidence(root.evidence)

  return {
    publicationDate: {
      value: asText(firstPresent(
        publication.value,
        publication.published_at,
        publication.date,
        typeof publicationValue === 'string' ? publicationValue : null,
        root.published_at,
        root.published_at_utc,
      )),
      source: asText(firstPresent(publication.source, publication.date_source, root.published_date_source)),
      confidence: asText(firstPresent(publication.confidence, root.published_date_confidence)),
      status: asText(firstPresent(publication.status, root.publication_date_status)),
    },
    score: {
      value: firstPresent(
        score.total,
        score.total_score,
        score.value,
        primitiveScore,
        root.total_score,
      ) as string | number | null,
      status: asText(firstPresent(score.status, root.score_status)),
      methodologyVersion: asText(firstPresent(
        score.methodology_version,
        score.methodologyVersion,
        root.score_methodology_version,
        root.methodology_version,
      )),
    },
    evidence: {
      status: asText(firstPresent(evidence?.status, root.screenshot_status, root.evidence_status)),
      screenshotUrl: asText(firstPresent(
        selectedScreenshot?.url,
        selectedScreenshot?.screenshot_url,
        evidence?.screenshot_url,
        evidence?.url,
        evidence?.download_url,
        root.screenshot_url,
      )),
      thumbnailUrl: asText(firstPresent(
        selectedThumbnail?.url,
        selectedThumbnail?.thumbnail_url,
        evidence?.thumbnail_url,
        evidence?.thumbnail,
        root.screenshot_thumbnail_url,
      )),
      capturedAt: asText(firstPresent(evidence?.captured_at, root.captured_at)),
    },
  }
}

const normalizeRecord = (payload: unknown, index: number): CoverageRecord => {
  const item = isObject(payload) ? payload : {}
  const details = normalizeCoverageDetails(item)
  const id = firstPresent(item.id, item.summary_id, item.article_id, `record-${index}`)
  return {
    ...details,
    id: typeof id === 'number' || typeof id === 'string' ? id : `record-${index}`,
    clientName: asText(firstPresent(item.client_name, item.client)),
    title: asText(item.title),
    url: asText(firstPresent(item.url, item.final_url, item.canonical_url)),
    publication: asText(firstPresent(item.publication, item.publication_name, item.domain)),
    generatedAt: asText(firstPresent(item.generated_at, item.created_at, item.report_generated_at)),
  }
}

const normalizeOptions = (payload: unknown, keys: string[]) => {
  const root = isObject(payload) ? payload : {}
  const values = Array.isArray(payload) ? payload : (Array.isArray(root.items) ? root.items : [])
  const normalized = values.flatMap(item => {
    if (typeof item === 'string' || typeof item === 'number') return [String(item)]
    if (!isObject(item)) return []
    for (const key of keys) {
      const value = asText(item[key])
      if (value) return [value]
    }
    return []
  })
  return [...new Set(normalized)].sort((left, right) => left.localeCompare(right))
}

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
  // Legacy copying must run synchronously inside the click's transient user
  // activation window. Keep the modern API attempt for richer browsers.
  const fallbackCopied = fallbackCopy(text)
  try {
    if (!navigator.clipboard?.writeText) throw new Error('Clipboard API unavailable')
    await Promise.race([
      navigator.clipboard.writeText(text),
      new Promise((_, reject) => window.setTimeout(() => reject(new Error('Clipboard timed out')), 1500)),
    ])
    return
  } catch {
    if (!fallbackCopied) throw new Error('Copy failed')
  }
}

const coverageQuery = (filters: RecordFilters, pagination?: { limit: number; offset: number }) => {
  const params = new URLSearchParams()
  if (filters.clientName) params.set('client_name', filters.clientName)
  if (filters.publication) params.set('publication', filters.publication)
  if (filters.startDate) params.set('start_date', filters.startDate)
  if (filters.endDate) params.set('end_date', filters.endDate)
  params.set('date_basis', filters.dateBasis)
  if (pagination) {
    params.set('limit', String(pagination.limit))
    params.set('offset', String(pagination.offset))
  }
  return params
}

const StatusLabel: React.FC<{ value: string | null; fallback?: string }> = ({ value, fallback = 'Unavailable' }) => (
  <span style={{
    display: 'inline-block',
    border: '1px solid #777',
    borderRadius: 999,
    padding: '2px 7px',
    fontSize: 12,
    whiteSpace: 'nowrap',
  }}>
    {humanize(value) || fallback}
  </span>
)

const EvidencePreview: React.FC<{ evidence: EvidenceDetails; title: string }> = ({ evidence, title }) => {
  const link = evidence.screenshotUrl || evidence.thumbnailUrl
  const thumbnail = evidence.thumbnailUrl || evidence.screenshotUrl
  const status = humanize(evidence.status) || pendingOrUnavailable(evidence.status)
  return (
    <div style={{ display: 'grid', gap: 5, justifyItems: 'start' }}>
      {thumbnail ? (
        <a href={link || thumbnail} target="_blank" rel="noreferrer" aria-label={`Open screenshot evidence for ${title}`}>
          <img
            src={thumbnail}
            alt={`Screenshot evidence for ${title}`}
            loading="lazy"
            style={{ display: 'block', width: 112, height: 70, objectFit: 'cover', border: '1px solid #777' }}
          />
        </a>
      ) : (
        <span style={mutedStyle}>{status}</span>
      )}
      {link && <a href={link} target="_blank" rel="noreferrer" style={{ fontSize: 12, color: '#000' }}>Open screenshot</a>}
      {evidence.capturedAt && <span style={mutedStyle}>Captured {formatDate(evidence.capturedAt, true)}</span>}
      {link && evidence.status && <StatusLabel value={evidence.status} />}
    </div>
  )
}

const GeneratedCoverageDetails: React.FC<{ details: CoverageDetails }> = ({ details }) => {
  const publicationLabel = formatDate(details.publicationDate.value)
    || pendingOrUnavailable(details.publicationDate.status)
  const scoreLabel = details.score.value !== null
    ? String(details.score.value)
    : pendingOrUnavailable(details.score.status)

  return (
    <div style={{
      border: '1px solid #9e9e9e',
      padding: 12,
      marginTop: 8,
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))',
      gap: 16,
    }}>
      <div>
        <strong style={{ display: 'block', marginBottom: 5 }}>Shift6 score</strong>
        <div style={{ fontSize: 22 }}>{scoreLabel}</div>
        <div style={{ marginTop: 4 }}>
          <StatusLabel value={details.score.status} fallback={details.score.value === null ? 'Unavailable' : 'Status unavailable'} />
        </div>
        <div style={{ ...mutedStyle, marginTop: 5 }}>
          {details.score.methodologyVersion
            ? `Methodology ${details.score.methodologyVersion}`
            : 'Methodology unavailable'}
        </div>
      </div>
      <div>
        <strong style={{ display: 'block', marginBottom: 5 }}>Publication date</strong>
        <div>{publicationLabel}</div>
        <div style={{ ...mutedStyle, marginTop: 5 }}>
          Source: {humanize(details.publicationDate.source) || 'Unavailable'}
        </div>
        <div style={mutedStyle}>
          Confidence: {humanize(details.publicationDate.confidence) || 'Unavailable'}
        </div>
      </div>
      <div>
        <strong style={{ display: 'block', marginBottom: 5 }}>Screenshot evidence</strong>
        <EvidencePreview evidence={details.evidence} title="generated coverage" />
      </div>
    </div>
  )
}

export const EmailApp: React.FC = () => {
  const [clientName, setClientName] = useState('')
  const [articleUrl, setArticleUrl] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<string>('')
  const [subject, setSubject] = useState<string>('')
  const [generatedDetails, setGeneratedDetails] = useState<CoverageDetails | null>(null)
  const [copyStatus, setCopyStatus] = useState<string>('')
  const [manualCopyText, setManualCopyText] = useState<string>('')
  const manualCopyRef = useRef<HTMLTextAreaElement | null>(null)
  const [error, setError] = useState<string>('')
  const [history, setHistory] = useState<HistoryItem[]>([])
  const [search, setSearch] = useState('')

  const [recordClients, setRecordClients] = useState<string[]>([])
  const [recordPublications, setRecordPublications] = useState<string[]>([])
  const [recordClient, setRecordClient] = useState('')
  const [recordPublication, setRecordPublication] = useState('')
  const [recordStartDate, setRecordStartDate] = useState('')
  const [recordEndDate, setRecordEndDate] = useState('')
  const [recordDateBasis, setRecordDateBasis] = useState<DateBasis>('published')
  const [records, setRecords] = useState<CoverageRecord[]>([])
  const [recordsTotal, setRecordsTotal] = useState(0)
  const [recordsOffset, setRecordsOffset] = useState(0)
  const [recordsLoading, setRecordsLoading] = useState(false)
  const [recordsError, setRecordsError] = useState('')
  const [exporting, setExporting] = useState(false)
  const recordsLimit = 25

  const recordFilters = () => ({
    clientName: recordClient,
    publication: recordPublication,
    startDate: recordStartDate,
    endDate: recordEndDate,
    dateBasis: recordDateBasis,
  })

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

  const loadRecordOptions = async () => {
    try {
      const [clientsResponse, publicationsResponse] = await Promise.all([
        fetch('/api/v1/email/records/clients'),
        fetch('/api/v1/email/records/publications'),
      ])
      if (clientsResponse.ok) {
        setRecordClients(normalizeOptions(await clientsResponse.json(), ['client_name', 'name', 'value']))
      }
      if (publicationsResponse.ok) {
        setRecordPublications(normalizeOptions(await publicationsResponse.json(), ['domain', 'publication', 'name', 'value']))
      }
    } catch {
      // Free-text filter fallbacks remain available if option discovery fails.
    }
  }

  const loadRecords = async (offset = recordsOffset, filters = recordFilters()) => {
    setRecordsLoading(true)
    setRecordsError('')
    try {
      const query = coverageQuery(filters, { limit: recordsLimit, offset })
      const response = await fetch(`/api/v1/email/records?${query.toString()}`)
      const text = await response.text()
      let payload: unknown
      try {
        payload = JSON.parse(text)
      } catch {
        throw new Error(text.slice(0, 160) || 'Coverage records returned an invalid response')
      }
      if (!response.ok) {
        const detail = isObject(payload) ? asText(payload.detail) : null
        throw new Error(detail || 'Unable to load coverage records')
      }
      const root = isObject(payload) ? payload : {}
      const items = Array.isArray(root.items) ? root.items : []
      const total = typeof root.total === 'number' ? root.total : items.length
      setRecords(items.map(normalizeRecord))
      setRecordsTotal(total)
      setRecordsOffset(offset)
    } catch (loadError) {
      setRecords([])
      setRecordsTotal(0)
      setRecordsError(loadError instanceof Error ? loadError.message : 'Unable to load coverage records')
    } finally {
      setRecordsLoading(false)
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => { void loadHistory() }, 250)
    return () => window.clearTimeout(timer)
  }, [clientName])

  useEffect(() => {
    void loadRecordOptions()
    void loadRecords(0)
  }, [])

  useEffect(() => {
    if (!manualCopyText) return
    manualCopyRef.current?.focus()
    manualCopyRef.current?.select()
  }, [manualCopyText])

  const onSubmit = async () => {
    setError(''); setResult(''); setSubject(''); setGeneratedDetails(null); setCopyStatus(''); setManualCopyText('')
    if (!clientName.trim() || !articleUrl.trim()) { setError('Please enter client and URL'); return }
    setLoading(true)
    try {
      const res = await fetch('/api/v1/email/summarize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID() },
        body: JSON.stringify({ client_name: clientName.trim(), article_url: articleUrl.trim() })
      })
      let j: UnknownRecord | null = null
      const txt = await res.text()
      try {
        const parsed = JSON.parse(txt)
        j = isObject(parsed) ? parsed : null
      } catch {
        throw new Error(txt?.slice(0, 200) || 'Non-JSON error')
      }
      if (!res.ok) throw new Error(asText(j?.detail) || 'Failed to summarize')
      setGeneratedDetails(normalizeCoverageDetails(j))
      if (j?.markdown) {
        const email = splitSubjectLine(String(j.body_markdown ?? j.markdown), asText(j.subject) || undefined)
        setResult(email.body)
        setSubject(email.subject)
      } else if (j?.status === 'accepted') {
        setResult('Request accepted. This is a placeholder; processing will return Markdown soon.')
      } else {
        setResult('No content returned.')
      }
      void loadHistory()
      void loadRecordOptions()
      void loadRecords(0)
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : 'Error')
    } finally {
      setLoading(false)
    }
  }

  const onCopy = async () => {
    const prefix = subject ? `Subject: ${subject}\n\n` : ''
    const emailText = `${prefix}${result}`
    setManualCopyText('')
    setCopyStatus('Copying…')
    try {
      await copyText(emailText)
      setCopyStatus('Copied')
      window.setTimeout(() => setCopyStatus(''), 2500)
    } catch {
      setManualCopyText(emailText)
      setCopyStatus('Clipboard blocked — press Cmd+C or Control+C below')
    }
  }

  const openSummary = async (summaryId?: number | null) => {
    if (!summaryId) return
    try {
      const client = clientName.trim()
      if (!client) return
      const response = await fetch(`/api/v1/email/summary/${summaryId}?client_name=${encodeURIComponent(client)}`)
      const payload = await response.json()
      if (response.ok && payload?.markdown) {
        const email = splitSubjectLine(String(payload.body_markdown ?? payload.markdown), payload.subject)
        setResult(email.body)
        setSubject(email.subject)
        setGeneratedDetails(normalizeCoverageDetails(payload))
      }
    } catch {}
  }

  const onSearch = async () => {
    const q = search.trim()
    if (!q) { void loadHistory(); return }
    const client = clientName.trim()
    if (!client) { setError('Enter a client name before searching history'); return }
    try {
      const response = await fetch(`/api/v1/email/history/search?q=${encodeURIComponent(q)}&client_name=${encodeURIComponent(client)}`)
      const payload = await response.json()
      if (response.ok && Array.isArray(payload.items)) setHistory(payload.items)
    } catch {}
  }

  const applyRecordFilters = () => {
    if (recordStartDate && recordEndDate && recordStartDate > recordEndDate) {
      setRecordsError('Start date must be on or before end date.')
      return
    }
    setRecordsOffset(0)
    void loadRecords(0)
  }

  const clearRecordFilters = () => {
    const clearedFilters: RecordFilters = {
      clientName: '',
      publication: '',
      startDate: '',
      endDate: '',
      dateBasis: 'published',
    }
    setRecordClient('')
    setRecordPublication('')
    setRecordStartDate('')
    setRecordEndDate('')
    setRecordDateBasis('published')
    setRecordsOffset(0)
    void loadRecords(0, clearedFilters)
  }

  const downloadCsv = async () => {
    setExporting(true)
    setRecordsError('')
    try {
      const query = coverageQuery(recordFilters())
      const response = await fetch(`/api/v1/email/records/export.csv?${query.toString()}`)
      if (!response.ok) {
        const text = await response.text()
        throw new Error(text.slice(0, 160) || 'Unable to export coverage records')
      }
      const blob = await response.blob()
      const objectUrl = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = objectUrl
      link.download = `shift6-coverage-${new Date().toISOString().slice(0, 10)}.csv`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(objectUrl)
    } catch (exportError) {
      setRecordsError(exportError instanceof Error ? exportError.message : 'Unable to export coverage records')
    } finally {
      setExporting(false)
    }
  }

  return (
    <div style={{ padding: 24, maxWidth: 1400, margin: '0 auto' }}>
      <h2 style={{ marginTop: 0 }}>PR Coverage Email</h2>
      <div style={{ border: '1px solid #9e9e9e', padding: 16, display: 'grid', gap: 8 }}>
        <input value={clientName} onChange={event => setClientName(event.target.value)} placeholder="Client name" aria-label="Client name" style={controlStyle} />
        <input value={articleUrl} onChange={event => setArticleUrl(event.target.value)} placeholder="Article URL" aria-label="Article URL" style={controlStyle} />
        <button onClick={onSubmit} disabled={loading} style={controlStyle}>{loading ? 'Processing…' : 'Generate'}</button>
        {error && <div role="alert" style={{ color: '#b00000' }}>{error}</div>}
      </div>

      {result && (
        <div style={{ marginTop: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <h3 style={{ margin: 0 }}>Generated Email</h3>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              {copyStatus && <span role="status" aria-live="polite" style={{ fontSize: 13 }}>{copyStatus}</span>}
              <button onClick={onCopy} disabled={copyStatus === 'Copying…'} style={controlStyle}>Copy subject + email</button>
            </div>
          </div>
          {generatedDetails && <GeneratedCoverageDetails details={generatedDetails} />}
          {manualCopyText && (
            <div style={{ border: '2px solid #000', padding: 8, marginTop: 8 }}>
              <label htmlFor="copy-ready-email" style={{ display: 'block', marginBottom: 6 }}>
                The complete email is selected. Press Cmd+C or Control+C to copy it.
              </label>
              <textarea
                id="copy-ready-email"
                ref={manualCopyRef}
                value={manualCopyText}
                readOnly
                rows={8}
                onFocus={event => event.currentTarget.select()}
                style={{ width: '100%', boxSizing: 'border-box', border: '1px solid #000', padding: 8 }}
              />
              <button onClick={() => { setManualCopyText(''); setCopyStatus('') }} style={{ ...controlStyle, marginTop: 6 }}>Close</button>
            </div>
          )}
          <div style={{ border: '1px solid #9e9e9e', padding: 12, marginTop: 8 }}>
            <div style={{ marginBottom: 12 }}><strong>Subject:</strong> {subject}</div>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{result}</ReactMarkdown>
          </div>
        </div>
      )}

      <section style={{ marginTop: 24 }}>
        <h3 style={{ margin: 0 }}>History</h3>
        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          <input value={search} onChange={event => setSearch(event.target.value)} placeholder="Search coverage…" aria-label="Search coverage history" style={{ ...controlStyle, flex: 1 }} />
          <button onClick={onSearch} style={controlStyle}>Search</button>
        </div>
        <ul style={{ listStyle: 'none', padding: 0, marginTop: 8 }}>
          {history.map(item => (
            <li key={item.summary_id || item.id} style={{ display: 'flex', gap: 8, alignItems: 'center', borderTop: '1px solid #9e9e9e', padding: '6px 0' }}>
              <button onClick={() => openSummary(item.summary_id || undefined)} style={{ ...controlStyle, minHeight: 0, padding: '2px 6px' }}>Open</button>
              <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.title || item.url}</span>
              <span style={{ color: '#555', fontSize: 12 }}>{item.domain}</span>
              <span style={{ color: '#777', fontSize: 12 }}>{item.created_at?.slice(0, 19).replace('T', ' ')}</span>
            </li>
          ))}
        </ul>
      </section>

      <section style={{ marginTop: 32, borderTop: '3px solid #000', paddingTop: 20 }} aria-labelledby="coverage-records-heading">
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'baseline', flexWrap: 'wrap' }}>
          <div>
            <h3 id="coverage-records-heading" style={{ margin: 0 }}>Coverage Records</h3>
            <p style={{ margin: '4px 0 0', color: '#555' }}>Filter durable placement evidence and export the same records to CSV.</p>
          </div>
          <button onClick={downloadCsv} disabled={exporting || recordsLoading} style={controlStyle}>
            {exporting ? 'Preparing CSV…' : 'Download CSV'}
          </button>
        </div>

        <div style={{
          border: '1px solid #9e9e9e',
          padding: 12,
          marginTop: 12,
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))',
          gap: 10,
          alignItems: 'end',
        }}>
          <label style={{ display: 'grid', gap: 4 }}>
            <span style={{ fontSize: 13, fontWeight: 600 }}>Client</span>
            <input
              list="coverage-record-clients"
              value={recordClient}
              onChange={event => setRecordClient(event.target.value)}
              placeholder="All clients"
              style={controlStyle}
            />
            <datalist id="coverage-record-clients">
              {recordClients.map(client => <option value={client} key={client} />)}
            </datalist>
          </label>
          <label style={{ display: 'grid', gap: 4 }}>
            <span style={{ fontSize: 13, fontWeight: 600 }}>Publication</span>
            <input
              list="coverage-record-publications"
              value={recordPublication}
              onChange={event => setRecordPublication(event.target.value)}
              placeholder="All publications"
              style={controlStyle}
            />
            <datalist id="coverage-record-publications">
              {recordPublications.map(publication => <option value={publication} key={publication} />)}
            </datalist>
          </label>
          <label style={{ display: 'grid', gap: 4 }}>
            <span style={{ fontSize: 13, fontWeight: 600 }}>Start date</span>
            <input type="date" value={recordStartDate} onChange={event => setRecordStartDate(event.target.value)} style={controlStyle} />
          </label>
          <label style={{ display: 'grid', gap: 4 }}>
            <span style={{ fontSize: 13, fontWeight: 600 }}>End date</span>
            <input type="date" value={recordEndDate} onChange={event => setRecordEndDate(event.target.value)} style={controlStyle} />
          </label>
          <label style={{ display: 'grid', gap: 4 }}>
            <span style={{ fontSize: 13, fontWeight: 600 }}>Date basis</span>
            <select value={recordDateBasis} onChange={event => setRecordDateBasis(event.target.value as DateBasis)} style={controlStyle}>
              <option value="published">Publication date</option>
              <option value="captured">Screenshot capture date</option>
              <option value="generated">Report generated</option>
            </select>
          </label>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={applyRecordFilters} disabled={recordsLoading} style={{ ...controlStyle, flex: 1 }}>Apply</button>
            <button onClick={clearRecordFilters} disabled={recordsLoading} style={{ ...controlStyle, flex: 1 }}>Clear</button>
          </div>
        </div>

        {recordsError && <div role="alert" style={{ color: '#b00000', marginTop: 10 }}>{recordsError}</div>}
        <div role="status" aria-live="polite" style={{ marginTop: 10, fontSize: 13, color: '#555' }}>
          {recordsLoading
            ? 'Loading coverage records…'
            : `${recordsTotal} record${recordsTotal === 1 ? '' : 's'}${recordsTotal > 0 ? ` — showing ${recordsOffset + 1}–${Math.min(recordsOffset + records.length, recordsTotal)}` : ''}`}
        </div>

        {!recordsLoading && !recordsError && records.length === 0 && (
          <div style={{ border: '1px solid #9e9e9e', padding: 16, marginTop: 8 }}>No coverage records match these filters.</div>
        )}

        {records.length > 0 && (
          <div style={{ overflowX: 'auto', marginTop: 8, border: '1px solid #9e9e9e' }}>
            <table style={{ width: '100%', minWidth: 1080, borderCollapse: 'collapse', textAlign: 'left' }}>
              <thead>
                <tr style={{ background: '#f1f1f1' }}>
                  {['Coverage', 'Publication', 'Publication date', 'Generated', 'Shift6 score', 'Screenshot'].map(label => (
                    <th key={label} scope="col" style={{ padding: 9, borderBottom: '2px solid #000', verticalAlign: 'bottom' }}>{label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {records.map(record => {
                  const publicationDate = formatDate(record.publicationDate.value)
                    || pendingOrUnavailable(record.publicationDate.status)
                  const score = record.score.value !== null
                    ? String(record.score.value)
                    : pendingOrUnavailable(record.score.status)
                  const title = record.title || record.url || 'Untitled coverage'
                  return (
                    <tr key={record.id} style={{ borderTop: '1px solid #bbb' }}>
                      <td style={{ padding: 9, verticalAlign: 'top', maxWidth: 280 }}>
                        {record.url
                          ? <a href={record.url} target="_blank" rel="noreferrer" style={{ color: '#000', fontWeight: 600 }}>{title}</a>
                          : <strong>{title}</strong>}
                        <div style={{ ...mutedStyle, marginTop: 5 }}>{record.clientName || 'Client unavailable'}</div>
                      </td>
                      <td style={{ padding: 9, verticalAlign: 'top' }}>{record.publication || 'Unavailable'}</td>
                      <td style={{ padding: 9, verticalAlign: 'top' }}>
                        <div>{publicationDate}</div>
                        <div style={{ ...mutedStyle, marginTop: 4 }}>
                          Source: {humanize(record.publicationDate.source) || 'Unavailable'}
                        </div>
                        <div style={mutedStyle}>
                          Confidence: {humanize(record.publicationDate.confidence) || 'Unavailable'}
                        </div>
                      </td>
                      <td style={{ padding: 9, verticalAlign: 'top' }}>
                        {formatDate(record.generatedAt, true) || 'Unavailable'}
                      </td>
                      <td style={{ padding: 9, verticalAlign: 'top' }}>
                        <div style={{ fontSize: 20 }}>{score}</div>
                        <div style={{ marginTop: 4 }}>
                          <StatusLabel value={record.score.status} fallback={record.score.value === null ? 'Unavailable' : 'Status unavailable'} />
                        </div>
                        <div style={{ ...mutedStyle, marginTop: 5 }}>
                          {record.score.methodologyVersion
                            ? `Methodology ${record.score.methodologyVersion}`
                            : 'Methodology unavailable'}
                        </div>
                      </td>
                      <td style={{ padding: 9, verticalAlign: 'top' }}>
                        <EvidencePreview evidence={record.evidence} title={title} />
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        {recordsTotal > recordsLimit && (
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 10 }}>
            <button
              onClick={() => void loadRecords(Math.max(0, recordsOffset - recordsLimit))}
              disabled={recordsLoading || recordsOffset === 0}
              style={controlStyle}
            >
              Previous
            </button>
            <button
              onClick={() => void loadRecords(recordsOffset + recordsLimit)}
              disabled={recordsLoading || recordsOffset + records.length >= recordsTotal}
              style={controlStyle}
            >
              Next
            </button>
          </div>
        )}
      </section>
    </div>
  )
}
