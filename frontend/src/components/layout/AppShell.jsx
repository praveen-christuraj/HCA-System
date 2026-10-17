import { useEffect } from 'react'
import { Link, useLocation } from 'react-router-dom'
import TopNavigation from './TopNavigation'
import UserMenu from './UserMenu'
import { findNavigationItem, hiddenRouteLabels } from '../../data/navigationItems'
import { logUiAction } from '../../utils/actionLogger'

const routeLabel = (pathname) => {
  if (hiddenRouteLabels[pathname]) return hiddenRouteLabels[pathname]
  const match = findNavigationItem(pathname)
  if (match) return match.item.label
  if (pathname.startsWith('/modules/')) return 'Module Dashboard'
  return 'Application'
}

// Avoid duplicate page-visit records in React StrictMode while still logging
// each real navigation (owner rule 1).
let lastLoggedPath = null

export default function AppShell({ loggedInUser, onLogout, children }) {
  const location = useLocation()

  useEffect(() => {
    if (lastLoggedPath === location.pathname) return
    lastLoggedPath = location.pathname
    logUiAction(routeLabel(location.pathname), 'Open Page', { path: location.pathname })
  }, [location.pathname])

  return (
    <div className="app-shell">
      <a href="#main-content" className="skip-link">
        Skip to main content
      </a>

      <header className="app-topbar no-print">
        <div className="app-topbar-inner">
          <Link to="/" className="app-brand" aria-label="HCA System home">
            <span className="app-brand-mark" aria-hidden="true">
              HCA
            </span>
            <span className="app-brand-text">
              <strong>HCA System</strong>
              <span>Hydrocarbon accounting &amp; inventory management</span>
            </span>
          </Link>

          <div className="app-topbar-utilities">
            <UserMenu loggedInUser={loggedInUser} onLogout={onLogout} />
          </div>
        </div>

        <div className="app-navbar">
          <div className="app-navbar-inner">
            <TopNavigation />
          </div>
        </div>
      </header>

      <main id="main-content" className="app-main" tabIndex={-1}>
        {children}
      </main>

      <footer className="app-footer no-print">
        <span>
          <span className="footer-strong">HCA System</span> · every action is recorded in the
          audit trail
        </span>
        <span>
          Signed in as {loggedInUser?.username} · {new Date().getFullYear()}
        </span>
      </footer>
    </div>
  )
}
