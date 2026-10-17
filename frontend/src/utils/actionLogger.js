/*
 * Client-side action log (owner rule 1).
 *
 * Backend mutations, page visits and UI actions must all be persisted. This
 * module posts UI events to POST /api/audit/ui-events. When no session exists
 * yet (login screen theme change), events are queued in sessionStorage and
 * flushed immediately after a successful sign-in. Nothing sensitive is sent.
 */
import { API_BASE_URL } from '../api/apiClient'
import { getStoredAccessToken } from '../api/authToken'

const PENDING_KEY = 'hca.pendingUiEvents'
const MAX_PENDING = 100

let currentUser = null

export const setActionLogUser = (user) => {
  currentUser = user
    ? { id: user.id, username: user.username, fullName: user.fullName || user.full_name || '' }
    : null
}

const readPending = () => {
  try {
    const raw = window.sessionStorage.getItem(PENDING_KEY)
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

const writePending = (entries) => {
  try {
    window.sessionStorage.setItem(PENDING_KEY, JSON.stringify(entries.slice(-MAX_PENDING)))
  } catch {
    // Storage unavailable — nothing else to do.
  }
}

const send = async (event) => {
  const token = getStoredAccessToken()
  if (!token) return false
  try {
    const response = await fetch(`${API_BASE_URL}/audit/ui-events`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(event),
      keepalive: true,
    })
    return response.ok
  } catch {
    return false
  }
}

export const logUiAction = (module, action, details = undefined) => {
  const event = {
    module: String(module || 'Application'),
    action: String(action || 'Action'),
    route:
      typeof window !== 'undefined' && window.location ? window.location.pathname : undefined,
    details: details === undefined ? undefined : details,
  }

  send(event).then((sent) => {
    if (!sent) {
      writePending([...readPending(), event])
    }
  })

  return event
}

export const flushPendingUiEvents = async () => {
  const pending = readPending()
  if (pending.length === 0) return
  const remaining = []
  for (const event of pending) {
    // eslint-disable-next-line no-await-in-loop
    const sent = await send(event)
    if (!sent) remaining.push(event)
  }
  writePending(remaining)
}

export const getActionLogUser = () => currentUser
