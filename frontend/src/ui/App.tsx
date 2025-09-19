import React, { useEffect, useState } from 'react'

export const App: React.FC = () => {
  const [health, setHealth] = useState<string>('checking…')
  useEffect(() => {
    fetch(import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/health')
      .then(r => r.json())
      .then(d => setHealth(d.status ?? 'ok'))
      .catch(() => setHealth('error'))
  }, [])
  return (
    <div style={{ fontFamily: 'system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif', color: '#000', background: '#fff', minHeight: '100vh' }}>
      <header style={{ borderBottom: '1px solid #e5e5e5', padding: '16px 24px' }}>
        <h1 style={{ margin: 0, fontWeight: 600 }}>Shift6 – Client Quote Generator</h1>
        <div style={{ fontSize: 14, color: '#555' }}>API health: {health}</div>
      </header>
      <main style={{ padding: 24 }}>
        <p>Frontend scaffold ready. Panels and chat UI coming next.</p>
      </main>
    </div>
  )
}
