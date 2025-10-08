import React from 'react'
import { createRoot } from 'react-dom/client'
// Quote Generator moved into its own folder
import { BrowserRouter, Routes, Route, NavLink, Navigate } from 'react-router-dom'
import { EmailApp } from './ui/email/EmailApp'
import { SettingsApp } from './ui/settings/SettingsApp'
import { QuotesApp } from './ui/quotes/QuotesApp'

const root = createRoot(document.getElementById('root')!)
root.render(
  <React.StrictMode>
    <BrowserRouter>
      <div style={{ fontFamily: 'system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif' }}>
        <nav style={{ display: 'flex', gap: 24, padding: '12px 16px', borderBottom: '1px solid #9e9e9e', alignItems: 'center' }}>
          {[
            { to: '/email', label: 'Email Generator' },
            { to: '/quotes', label: 'Quote Generator' },
          ].map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              style={({ isActive }) => ({
                color: '#000',
                textDecoration: 'none',
                padding: '6px 4px',
                borderBottom: isActive ? '2px solid #000' : '2px solid transparent',
                cursor: 'pointer',
              })}
              onMouseOver={(e) => ((e.currentTarget.style.textDecoration = 'underline'))}
              onMouseOut={(e) => ((e.currentTarget.style.textDecoration = 'none'))}
            >
              {item.label}
            </NavLink>
          ))}
          <div style={{ marginLeft: 'auto' }}>
            <NavLink
              to="/settings"
              style={({ isActive }) => ({
                color: '#000',
                textDecoration: 'none',
                padding: '6px 4px',
                borderBottom: isActive ? '2px solid #000' : '2px solid transparent',
                cursor: 'pointer',
              })}
              onMouseOver={(e) => ((e.currentTarget.style.textDecoration = 'underline'))}
              onMouseOut={(e) => ((e.currentTarget.style.textDecoration = 'none'))}
            >
              Settings
            </NavLink>
          </div>
        </nav>
        <Routes>
          <Route path="/" element={<Navigate to="/email" replace />} />
          <Route path="/email" element={<EmailApp />} />
          <Route path="/quotes" element={<QuotesApp />} />
          <Route path="/settings" element={<SettingsApp />} />
        </Routes>
      </div>
    </BrowserRouter>
  </React.StrictMode>
)
