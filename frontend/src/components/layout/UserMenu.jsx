import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import Icon from '../common/Icon'
import { THEME_OPTIONS, useTheme } from '../../context/ThemeProvider'
import { usePermissions } from '../../hooks/usePermissions'

const THEME_ICONS = { light: 'sun', dark: 'moon', system: 'monitor' }

const initialsOf = (user) => {
  const source = String(user?.full_name || user?.fullName || user?.username || '?').trim()
  const parts = source.split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '?'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

export default function UserMenu({ loggedInUser, onLogout }) {
  const [open, setOpen] = useState(false)
  const wrapperRef = useRef(null)
  const { preference, resolvedTheme, setPreference } = useTheme()
  const { hasPermission } = usePermissions()

  useEffect(() => {
    if (!open) return undefined
    const handlePointer = (event) => {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target)) setOpen(false)
    }
    const handleKey = (event) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', handlePointer)
    document.addEventListener('keydown', handleKey)
    return () => {
      document.removeEventListener('mousedown', handlePointer)
      document.removeEventListener('keydown', handleKey)
    }
  }, [open])

  const roleName =
    loggedInUser?.role?.role_name ||
    loggedInUser?.role_name ||
    (Array.isArray(loggedInUser?.roles) && loggedInUser.roles.length > 0
      ? loggedInUser.roles.map((role) => role.role_name).filter(Boolean).join(', ')
      : '') ||
    'No role'

  return (
    <div className="user-menu" ref={wrapperRef}>
      <button
        type="button"
        className="theme-quick-toggle"
        onClick={() => setPreference(resolvedTheme === 'dark' ? 'light' : 'dark')}
        aria-label={`Switch to ${resolvedTheme === 'dark' ? 'light' : 'dark'} theme`}
        title={`Switch to ${resolvedTheme === 'dark' ? 'light' : 'dark'} theme`}
      >
        <Icon name={resolvedTheme === 'dark' ? 'sun' : 'moon'} size={16} />
      </button>

      <button
        type="button"
        className={`user-menu-button ${open ? 'is-open' : ''}`.trim()}
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <span className="user-avatar" aria-hidden="true">
          {initialsOf(loggedInUser)}
        </span>
        <span className="user-menu-identity">
          <strong>{loggedInUser?.full_name || loggedInUser?.username}</strong>
          <span>{roleName}</span>
        </span>
        <Icon name="chevronDown" size={13} className="user-menu-chevron" />
      </button>

      {open && (
        <div className="user-menu-popover" role="menu" aria-label="User menu">
          <div className="user-menu-card">
            <span className="user-avatar user-avatar-lg" aria-hidden="true">
              {initialsOf(loggedInUser)}
            </span>
            <div>
              <strong>{loggedInUser?.full_name || loggedInUser?.username}</strong>
              <div className="user-menu-sub">@{loggedInUser?.username}</div>
              <div className="user-menu-sub">{roleName}</div>
            </div>
          </div>

          <div className="user-menu-section">
            <div className="user-menu-section-title">Theme</div>
            <div className="theme-switcher" role="radiogroup" aria-label="Theme">
              {THEME_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  role="radio"
                  aria-checked={preference === option.value}
                  className={`theme-switcher-option ${preference === option.value ? 'is-selected' : ''}`.trim()}
                  onClick={() => setPreference(option.value)}
                >
                  <Icon name={THEME_ICONS[option.value]} size={14} />
                  {option.label}
                </button>
              ))}
            </div>
          </div>

          <div className="user-menu-section">
            <Link
              to="/"
              role="menuitem"
              className="user-menu-item"
              onClick={() => setOpen(false)}
            >
              <Icon name="home" size={16} />
              Portfolio dashboard
            </Link>
            {hasPermission('audit:read') && (
              <Link
                to="/audit"
                role="menuitem"
                className="user-menu-item"
                onClick={() => setOpen(false)}
              >
                <Icon name="history" size={16} />
                Audit trail
              </Link>
            )}
          </div>

          <div className="user-menu-section">
            <button
              type="button"
              role="menuitem"
              className="user-menu-item user-menu-logout"
              onClick={() => {
                setOpen(false)
                onLogout()
              }}
            >
              <Icon name="logout" size={16} />
              Sign out
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
