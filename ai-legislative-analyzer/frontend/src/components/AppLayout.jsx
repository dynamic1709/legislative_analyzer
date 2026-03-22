import React from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { LayoutDashboard, UserRound, Upload, Sparkles } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import '../styles/pages.css'

const steps = [
  { path: '/', labelKey: 'home', icon: LayoutDashboard },
  { path: '/profile', labelKey: 'citizenProfile', icon: UserRound },
  { path: '/upload', labelKey: 'uploadDocument', icon: Upload },
  { path: '/analysis', labelKey: 'comprehensiveAnalysis', icon: Sparkles },
]

export default function AppLayout() {
  const location = useLocation()
  const { t } = useTranslation()

  return (
    <div className="app-layout-shell">
      <header className="app-nav">
        <div className="app-brand">
          <div className="brand-mark">LA</div>
          <div>
            <p className="eyebrow">Citizen Policy Intelligence</p>
            <h1>AI Legislative Analyzer</h1>
          </div>
        </div>

        <nav className="app-nav-links" aria-label="Primary navigation">
          {steps.map(({ path, labelKey, icon: Icon }) => {
            const isActive =
              path === '/'
                ? location.pathname === '/'
                : location.pathname.startsWith(path)

            return (
              <NavLink
                key={path}
                to={path}
                className={`nav-chip ${isActive ? 'nav-chip-active' : ''}`}
              >
                <Icon size={16} />
                <span>{t(labelKey)}</span>
              </NavLink>
            )
          })}
        </nav>
      </header>

      <main className="app-page-content">
        <Outlet />
      </main>
    </div>
  )
}
