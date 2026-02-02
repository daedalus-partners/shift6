import React from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route, NavLink, Navigate } from 'react-router-dom'
import { EmailApp } from './ui/email/EmailApp'
import { CoverageApp } from './ui/coverage/CoverageApp'
import { QuotesApp } from './ui/quotes/QuotesApp'
import { SettingsApp } from './ui/settings/SettingsApp'

const root = createRoot(document.getElementById('root')!)
root.render(
  <React.StrictMode>
    <BrowserRouter>
      <div style={{ fontFamily: 'system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif' }}>
        <nav style={{ display: 'flex', gap: 24, padding: '12px 16px', borderBottom: '1px solid #9e9e9e', alignItems: 'center' }}>
          {[
            { to: '/email', label: 'Email Generator' },
            { to: '/coverage', label: 'Coverage Tracker' },
            { to: '/quotes', label: 'Quote Generator' },
            { to: 'https://shift6-buildout.onrender.com/', label: 'Task Manager', external: true },
          ].map((item) => (
            'external' in item && item.external ? (
              <a
                key={item.to}
                href={item.to}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  color: '#000',
                  textDecoration: 'none',
                  padding: '6px 4px',
                  borderBottom: '2px solid transparent',
                  cursor: 'pointer',
                  fontWeight: 'bold',
                }}
                onMouseOver={(e) => ((e.currentTarget.style.textDecoration = 'underline'))}
                onMouseOut={(e) => ((e.currentTarget.style.textDecoration = 'none'))}
              >
                {item.label} ↗
              </a>
            ) : (
              <NavLink
                key={item.to}
                to={item.to}
                style={({ isActive }) => ({
                  color: '#000',
                  textDecoration: 'none',
                  padding: '6px 4px',
                  borderBottom: isActive ? '2px solid #000' : '2px solid transparent',
                  cursor: 'pointer',
                  fontWeight: 'bold',
                })}
                onMouseOver={(e) => ((e.currentTarget.style.textDecoration = 'underline'))}
                onMouseOut={(e) => ((e.currentTarget.style.textDecoration = 'none'))}
              >
                {item.label}
              </NavLink>
            )
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
                fontWeight: 'bold',
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
          <Route path="/coverage" element={<CoverageApp />} />
          <Route path="/quotes" element={<QuotesApp />} />
          <Route path="/settings" element={<SettingsApp />} />
        </Routes>
      </div>
    </BrowserRouter>
  </React.StrictMode>
)
