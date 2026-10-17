import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getDashboardSummary } from '../api/dashboardApi'
import Icon from '../components/common/Icon'
import {
  Alert,
  formatDateTime,
  KpiCard,
  Loading,
  PageHead,
  StatusTag,
} from '../components/common/Ui'
import { logUiAction } from '../utils/actionLogger'

export default function Home() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const summary = await getDashboardSummary()
      setData(summary)
    } catch (loadError) {
      setError(loadError.message || 'Unable to load the dashboard')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  return (
    <div className="page">
      <PageHead
        eyebrow="HOME / PORTFOLIO"
        title="Portfolio overview"
        description="Live delivery status, access-control indicators and the most recent audited activity across the platform."
        actions={
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => {
              logUiAction('Portfolio Dashboard', 'Refresh Dashboard')
              load()
            }}
            disabled={loading}
          >
            <Icon name="refresh" size={15} />
            Refresh
          </button>
        }
      />

      {error && <Alert tone="danger">{error}</Alert>}

      {loading && !data ? (
        <Loading label="Loading portfolio dashboard…" />
      ) : (
        <>
          <section className="kpi-grid" aria-label="Portfolio KPIs">
            {(data?.kpis || []).map((kpi) => (
              <KpiCard key={kpi.key} label={kpi.label} value={kpi.value} context={kpi.context} />
            ))}
          </section>

          <section className="card">
            <div className="card-head">
              <div>
                <h2 className="card-title">Modules</h2>
                <p className="card-subtitle">
                  Module-wise dashboards. Planned modules are labelled honestly and are not
                  presented as delivered.
                </p>
              </div>
            </div>
            <div className="card-body">
              <div className="module-grid">
                {(data?.modules || []).map((module) => (
                  <article key={module.key} className="module-card">
                    <div className="module-card-head">
                      <div>
                        <h3 className="module-card-title">{module.name}</h3>
                      </div>
                      <StatusTag status={module.status} />
                    </div>
                    <p className="module-card-desc">{module.description}</p>
                    {module.metrics?.length > 0 && (
                      <div className="module-metrics">
                        {module.metrics.map((metric) => (
                          <div key={metric.label} className="module-metric">
                            <strong className="tnum">{metric.value}</strong>
                            <span>{metric.label}</span>
                          </div>
                        ))}
                      </div>
                    )}
                    <div className="module-card-foot">
                      <Link to={module.path} className="module-card-link">
                        Open module dashboard
                      </Link>
                      <Icon name="arrowRight" size={15} style={{ color: 'var(--text-muted)' }} />
                    </div>
                  </article>
                ))}
              </div>
            </div>
          </section>

          <section className="card">
            <div className="card-head">
              <div>
                <h2 className="card-title">Recent audited activity</h2>
                <p className="card-subtitle">
                  Every action is recorded with actor, module, outcome and timestamp.
                </p>
              </div>
              <Link to="/audit" className="btn btn-secondary btn-compact">
                Open audit trail
              </Link>
            </div>
            <div className="card-body flush">
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Timestamp</th>
                      <th>Actor</th>
                      <th>Module</th>
                      <th>Action</th>
                      <th>Category</th>
                      <th>Outcome</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(data?.recent_audit || []).length === 0 && (
                      <tr>
                        <td colSpan={6} className="muted">
                          No audited activity yet.
                        </td>
                      </tr>
                    )}
                    {(data?.recent_audit || []).map((entry) => (
                      <tr key={entry.id}>
                        <td className="nowrap tnum">{formatDateTime(entry.created_at)}</td>
                        <td>{entry.actor_username || 'system'}</td>
                        <td>{entry.module_name}</td>
                        <td className="cell-primary">{entry.action}</td>
                        <td>{entry.category}</td>
                        <td>
                          <StatusTag status={entry.outcome} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </section>
        </>
      )}
    </div>
  )
}
