import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, NavLink, useLocation } from 'react-router-dom'
import Icon from '../common/Icon'
import { findNavigationItem, navigationItems } from '../../data/navigationItems'
import { usePermissions } from '../../hooks/usePermissions'

/**
 * Top-side navigation with dropdown menus (owner rule 3).
 * Keyboard accessible, closes on Escape/outside click/route change and is
 * filtered by the user's permissions.
 */
export default function TopNavigation() {
  const { isAdmin, hasPermission } = usePermissions()
  const location = useLocation()
  const [openState, setOpenState] = useState({ index: null, path: location.pathname })
  const openIndex = openState.path === location.pathname ? openState.index : null
  const navRef = useRef(null)

  const setOpenIndex = useCallback(
    (value) => {
      setOpenState((current) => ({
        index: typeof value === 'function' ? value(current.index) : value,
        path: location.pathname,
      }))
    },
    [location.pathname],
  )

  const hasRequiredPermissions = useCallback(
    (item) => {
      if (isAdmin) return true
      if (item.permission && !hasPermission(item.permission)) return false
      if (item.anyPermission && !item.anyPermission.some(hasPermission)) return false
      if (item.allPermissions && !item.allPermissions.every(hasPermission)) return false
      return true
    },
    [isAdmin, hasPermission],
  )

  const close = useCallback(() => setOpenIndex(null), [setOpenIndex])

  useEffect(() => {
    if (openIndex === null) return undefined
    const handlePointer = (event) => {
      if (navRef.current && !navRef.current.contains(event.target)) close()
    }
    const handleKey = (event) => {
      if (event.key === 'Escape') {
        close()
        navRef.current
          ?.querySelector(`[data-nav-index="${openIndex}"]`)
          ?.focus()
      }
    }
    document.addEventListener('mousedown', handlePointer)
    document.addEventListener('keydown', handleKey)
    return () => {
      document.removeEventListener('mousedown', handlePointer)
      document.removeEventListener('keydown', handleKey)
    }
  }, [openIndex, close])

  const visibleGroups = navigationItems
    .map((group, index) => {
      if (group.type === 'link') {
        return hasRequiredPermissions(group) ? { ...group, index } : null
      }
      const items = isAdmin
        ? group.items
        : group.items.filter((item) => hasRequiredPermissions(item))
      return items.length > 0 ? { ...group, items, index } : null
    })
    .filter(Boolean)

  const activeMatch = findNavigationItem(location.pathname)
  const activePath = activeMatch?.item?.path || null
  const isGroupActive = (group) =>
    group.type !== 'link' && group.items.some((item) => item.path === activePath)

  const handleTopKeyDown = (event, position) => {
    if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return
    event.preventDefault()
    const buttons = Array.from(navRef.current?.querySelectorAll('[data-nav-top]') || [])
    const delta = event.key === 'ArrowRight' ? 1 : -1
    const next = buttons[(position + delta + buttons.length) % buttons.length]
    next?.focus()
    if (openIndex !== null) {
      const nextIndex = Number(next?.getAttribute('data-nav-index'))
      setOpenIndex(Number.isNaN(nextIndex) ? null : nextIndex)
    }
  }

  return (
    <nav className="top-nav" aria-label="Main navigation" ref={navRef}>
      <ul className="top-nav-list">
        {visibleGroups.map((group, position) => {
          if (group.type === 'link') {
            return (
              <li key={group.label} className="top-nav-item">
                <NavLink
                  to={group.path}
                  end={group.path === '/'}
                  className={({ isActive }) =>
                    `top-nav-link ${isActive ? 'is-active' : ''}`.trim()
                  }
                  data-nav-top="true"
                  onKeyDown={(event) => handleTopKeyDown(event, position)}
                >
                  {group.label}
                </NavLink>
              </li>
            )
          }

          const open = openIndex === group.index
          const active = isGroupActive(group)

          return (
            <li
              key={group.label}
              className={`top-nav-item has-menu ${open ? 'is-open' : ''}`.trim()}
            >
              <button
                type="button"
                className={`top-nav-link ${active ? 'is-active' : ''} ${open ? 'is-open' : ''}`.trim()}
                aria-haspopup="menu"
                aria-expanded={open}
                aria-controls={`top-nav-menu-${group.index}`}
                data-nav-top="true"
                data-nav-index={group.index}
                onClick={() => setOpenIndex(open ? null : group.index)}
                onKeyDown={(event) => handleTopKeyDown(event, position)}
              >
                {group.label}
                <Icon name="chevronDown" size={13} className="top-nav-chevron" />
              </button>

              {open && (
                <div
                  id={`top-nav-menu-${group.index}`}
                  className="top-nav-menu"
                  role="menu"
                >
                  {group.items.map((item) => (
                    <Link
                      key={item.path}
                      to={item.path}
                      role="menuitem"
                      className={`top-nav-menu-item ${item.path === activePath ? 'is-active' : ''}`.trim()}
                      onClick={close}
                    >
                      {item.label}
                    </Link>
                  ))}
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </nav>
  )
}
