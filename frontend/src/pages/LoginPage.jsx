import { useEffect, useMemo, useState } from 'react'
import { API_BASE_URL } from '../api/apiClient'
import { loginUser, requestPasswordReset, verifyLogin2FA } from '../api/authApi'
import Icon from '../components/common/Icon'
import { THEME_OPTIONS, useTheme } from '../context/ThemeProvider'

const calcPasswordStrength = (password) => {
  let score = 0
  if (password.length >= 8) score += 1
  if (password.length >= 12) score += 1
  if (/[a-z]/.test(password)) score += 1
  if (/[A-Z]/.test(password)) score += 1
  if (/[0-9]/.test(password)) score += 1
  if (/[^a-zA-Z0-9]/.test(password)) score += 1
  if (score <= 2) return { label: 'Weak', pct: 25, color: 'var(--danger)' }
  if (score <= 3) return { label: 'Fair', pct: 50, color: 'var(--warning)' }
  if (score <= 5) return { label: 'Good', pct: 75, color: 'var(--warning-text)' }
  return { label: 'Strong', pct: 100, color: 'var(--success)' }
}

const THEME_ICONS = { light: 'sun', dark: 'moon', system: 'monitor' }

function BrandMark({ size = 52 }) {
  return (
    <div className="login-brand-mark" style={{ width: size, height: size }} aria-hidden="true">
      <svg
        width={size * 0.54}
        height={size * 0.54}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M12 2L2 7l10 5 10-5-10-5z" />
        <path d="M2 17l10 5 10-5" />
        <path d="M2 12l10 5 10-5" />
      </svg>
    </div>
  )
}

export default function LoginPage({ onLogin }) {
  const { preference, setPreference } = useTheme()

  const [health, setHealth] = useState(null)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [twoFACode, setTwoFACode] = useState('')
  const [challenge, setChallenge] = useState(null)
  const [resetUsername, setResetUsername] = useState('')
  const [resetReason, setResetReason] = useState('')
  const [reset2FA, setReset2FA] = useState(false)
  const [showReset, setShowReset] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [successMsg, setSuccessMsg] = useState('')

  useEffect(() => {
    let active = true
    fetch(`${API_BASE_URL}/health`)
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (active) setHealth(data)
      })
      .catch(() => undefined)
    return () => {
      active = false
    }
  }, [])

  const pwStrength = useMemo(() => calcPasswordStrength(password), [password])
  const unseeded = health ? health.admin_seeded === false : false

  const clearMessages = () => {
    setError('')
    setSuccessMsg('')
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    clearMessages()

    if (!username.trim()) {
      setError('Username is required')
      return
    }
    if (!password.trim()) {
      setError('Password is required')
      return
    }

    try {
      setLoading(true)
      const loggedInUser = await loginUser(username, password)
      if (loggedInUser?.requires2FA) {
        setChallenge(loggedInUser)
        setTwoFACode('')
        return
      }
      onLogin(loggedInUser)
    } catch (loginError) {
      setError(loginError.message || 'Sign-in failed')
    } finally {
      setLoading(false)
    }
  }

  const handleVerify2FA = async (event) => {
    event.preventDefault()
    clearMessages()

    if (!challenge?.challengeId) {
      setError('The verification challenge is missing. Please sign in again.')
      setChallenge(null)
      return
    }
    if (!twoFACode.trim()) {
      setError('Authentication code is required')
      return
    }

    try {
      setLoading(true)
      const loggedInUser = await verifyLogin2FA(challenge.challengeId, twoFACode)
      onLogin(loggedInUser)
    } catch (verifyError) {
      setError(verifyError.message || 'Two-factor verification failed')
    } finally {
      setLoading(false)
    }
  }

  const handlePasswordReset = async (event) => {
    event.preventDefault()
    clearMessages()

    const target = (resetUsername || username || '').trim()
    if (!target) {
      setError('Username is required')
      return
    }

    try {
      setLoading(true)
      const response = await requestPasswordReset(target, resetReason, reset2FA)
      setSuccessMsg(response.message || 'Password reset request submitted.')
      setShowReset(false)
      setResetUsername('')
      setResetReason('')
      setReset2FA(false)
    } catch (resetError) {
      setError(resetError.message || 'Password reset request failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-page-new" aria-label="HCA System sign in">
      <aside className="login-left" aria-label="HCA System">
        <div className="login-left-inner">
          <header className="login-brand">
            <BrandMark />
            <div className="login-brand-copy">
              <h1 className="login-brand-title">
                <span>HYDROCARBON</span> <span>ACCOUNTING SYSTEM</span>
              </h1>
              <p className="login-brand-subtitle">
                Integrated Hydrocarbon Operations &amp; Inventory Management
              </p>
            </div>
          </header>

          <div className="login-story">
            <div className="login-story-accent" aria-hidden="true" />
            <h2 className="login-story-headline">
              <span>Precision. Integrity.</span> <span>Operational Excellence.</span>
            </h2>
            <p className="login-story-copy">
              Secure access to your operational data, inventory records, measurement
              workflows and reporting systems.
            </p>
          </div>

          <div className="login-values">
            ACCURACY · TRACEABILITY · SECURITY · INTELLIGENCE
          </div>
        </div>
      </aside>

      <main className="login-right" aria-label="Sign in form">
        <div className="login-theme-bar" role="radiogroup" aria-label="Colour theme">
          {THEME_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={preference === option.value}
              className={`login-theme-option ${preference === option.value ? 'is-selected' : ''}`.trim()}
              onClick={() => setPreference(option.value)}
              title={`${option.label} theme`}
            >
              <Icon name={THEME_ICONS[option.value]} size={14} />
              <span>{option.label}</span>
            </button>
          ))}
        </div>

        <div className="login-card-new">
          <div className="login-card-icon" aria-hidden="true">
            <svg
              width="24"
              height="24"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.1"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <rect x="3" y="11" width="18" height="10" rx="2" ry="2" />
              <circle cx="12" cy="5" r="2" />
              <path d="M12 7v4" />
            </svg>
          </div>

          <h2 className="login-card-title">Sign in</h2>
          <p className="login-card-subtitle">
            Enterprise hydrocarbon accounting workspace
          </p>

          {unseeded && (
            <div className="login-alert login-alert-warning" role="alert">
              <Icon name="alertTriangle" size={16} className="alert-icon" />
              <div>
                <strong>This deployment has no administrator yet.</strong> The backend seeds the
                administrator automatically when the Docker stack starts. Run{' '}
                <code className="login-code">docker compose up --build</code> or, on an existing
                container, <code className="login-code">python -m app.seed_admin</code>.
              </div>
            </div>
          )}

          {successMsg && (
            <div className="login-alert login-alert-success" role="status">
              <Icon name="checkCircle" size={16} className="alert-icon" />
              <div>{successMsg}</div>
              <button
                type="button"
                className="login-alert-close"
                onClick={() => setSuccessMsg('')}
                aria-label="Dismiss message"
              >
                ×
              </button>
            </div>
          )}

          {error && (
            <div className="login-alert login-alert-error" role="alert">
              <Icon name="alertCircle" size={16} className="alert-icon" />
              <div>{error}</div>
              <button
                type="button"
                className="login-alert-close"
                onClick={() => setError('')}
                aria-label="Dismiss error"
              >
                ×
              </button>
            </div>
          )}

          {challenge ? (
            <form className="login-form" onSubmit={handleVerify2FA} aria-label="Two-factor authentication">
              <div className="login-info-box">
                Enter the authentication code for{' '}
                <strong>
                  {challenge.userHint?.full_name || challenge.userHint?.username || username}
                </strong>
                .
              </div>

              <div className="login-field">
                <label htmlFor="login-2fa" className="login-label">
                  Authentication code
                </label>
                <input
                  id="login-2fa"
                  type="text"
                  value={twoFACode}
                  onChange={(event) => setTwoFACode(event.target.value)}
                  placeholder="6-digit code or backup code"
                  autoFocus
                  autoComplete="one-time-code"
                  className="login-input"
                  aria-required="true"
                />
              </div>

              <div className="login-form-actions">
                <button type="submit" disabled={loading} className="login-btn-primary">
                  {loading ? 'Verifying…' : 'Verify and sign in'}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setChallenge(null)
                    clearMessages()
                  }}
                  disabled={loading}
                  className="login-btn-secondary"
                >
                  Cancel
                </button>
              </div>
            </form>
          ) : (
            <>
              <form className="login-form" onSubmit={handleSubmit} aria-label="Workspace sign in">
                <div className="login-field">
                  <label htmlFor="login-username" className="login-label">
                    Username
                  </label>
                  <input
                    id="login-username"
                    name="username"
                    type="text"
                    required
                    value={username}
                    onChange={(event) => setUsername(event.target.value)}
                    placeholder="Enter your username"
                    autoComplete="username"
                    className="login-input"
                    aria-required="true"
                    autoFocus
                  />
                </div>

                <div className="login-field">
                  <label htmlFor="login-password" className="login-label">
                    Password
                  </label>
                  <div className="password-input-wrapper">
                    <input
                      id="login-password"
                      name="password"
                      type={showPassword ? 'text' : 'password'}
                      required
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      placeholder="Enter your password"
                      autoComplete="current-password"
                      className="login-input"
                      aria-required="true"
                    />
                    <button
                      type="button"
                      className="login-password-toggle"
                      onClick={() => setShowPassword((value) => !value)}
                      aria-label={showPassword ? 'Hide password' : 'Show password'}
                    >
                      <Icon name={showPassword ? 'eyeOff' : 'eye'} size={17} />
                    </button>
                  </div>
                  {password && (
                    <div className="password-strength" aria-live="polite">
                      <div className="password-strength-track">
                        <div
                          className="password-strength-fill"
                          style={{ width: `${pwStrength.pct}%`, background: pwStrength.color }}
                        />
                      </div>
                      <span
                        className="password-strength-label"
                        style={{ color: pwStrength.color }}
                      >
                        {pwStrength.label}
                      </span>
                    </div>
                  )}
                </div>

                <button
                  type="submit"
                  disabled={loading}
                  className="login-btn-primary"
                  aria-label="Sign in to workspace"
                >
                  {loading ? (
                    <>
                      <svg
                        width="17"
                        height="17"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2.5"
                        strokeLinecap="round"
                        className="login-spinner"
                        aria-hidden="true"
                      >
                        <circle cx="12" cy="12" r="10" strokeDasharray="60" strokeDashoffset="20" />
                      </svg>
                      Signing in…
                    </>
                  ) : (
                    <>
                      Sign in to workspace
                      <Icon name="arrowRight" size={17} />
                    </>
                  )}
                </button>
              </form>

              <div className="login-reset-area">
                {!showReset ? (
                  <button
                    type="button"
                    onClick={() => {
                      setShowReset(true)
                      clearMessages()
                    }}
                    className="login-link-btn"
                    aria-expanded={showReset}
                  >
                    Reset password
                  </button>
                ) : (
                  <form
                    onSubmit={handlePasswordReset}
                    id="login-reset-form"
                    className="login-form"
                    aria-label="Password reset request"
                  >
                    <div className="login-field">
                      <label htmlFor="login-reset-user" className="login-label">
                        Username
                      </label>
                      <input
                        id="login-reset-user"
                        type="text"
                        value={resetUsername}
                        onChange={(event) => setResetUsername(event.target.value)}
                        placeholder={username || 'Enter username'}
                        autoFocus
                        className="login-input"
                      />
                    </div>
                    <div className="login-field">
                      <label htmlFor="login-reset-reason" className="login-label">
                        Reason (optional)
                      </label>
                      <input
                        id="login-reset-reason"
                        type="text"
                        value={resetReason}
                        onChange={(event) => setResetReason(event.target.value)}
                        placeholder="Why you need a reset"
                        className="login-input"
                      />
                    </div>
                    <label className="login-checkbox-label">
                      <input
                        type="checkbox"
                        checked={reset2FA}
                        onChange={(event) => setReset2FA(event.target.checked)}
                      />
                      Require two-factor verification
                    </label>
                    <div className="login-form-actions">
                      <button
                        type="button"
                        onClick={() => setShowReset(false)}
                        className="login-btn-secondary"
                      >
                        Cancel
                      </button>
                      <button type="submit" disabled={loading} className="login-btn-primary">
                        {loading ? 'Sending…' : 'Submit request'}
                      </button>
                    </div>
                  </form>
                )}
              </div>
            </>
          )}
        </div>

        <footer className="login-footer">
          <strong>HCA System</strong> · Hydrocarbon Accounting{health ? ` · v${health.version}` : ''}
          {health === null ? ' · API unavailable' : ''}
        </footer>
      </main>
    </div>
  )
}
