import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getModuleDashboard } from '../api/dashboardApi'
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

export default function ModuleDashboard() {
  const { moduleKey } = useParams()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    setData(null)
    try {
      const response = await getModuleDashboard(moduleKey)
      setData(response)
    } catch (loadError) {
      setError(loadError.message || 'Unable to load the module dashboard')
    } finally {
      setLoading(false)
    }
  }, [moduleKey])

  useEffect(() => {
    load()
  }, [load])

  const module = data?.module
  const maxBreakdown = Math.max(1, ...(data?.breakdown || []).map((item) => item.value || 0))

  return (
    <div className="page">
      <PageHead
        eyebrow={`MODULE / ${String(module?.name || moduleKey).toUpperCase()}`}
        title={module?.name || 'Module dashboard'}
        description={module?.description}
        actions={
          <>
            <Link to="/" className="btn btn-secondary">
              <Icon name="home" size={15} />
              Portfolio
            </Link>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => {
                logUiAction(module?.name || 'Module Dashboard', 'Refresh Dashboard')
                load()
              }}
              disabled={loading}
            >
              <Icon name="refresh" size={15} />
              Refresh
            </button>
          </>
        }
      />

      {error && <Alert tone="danger">{error}</Alert>}

      {loading ? (
        <Loading label="Loading module dashboard…" />
      ) : (
        module && (
          <>
            <section className="card">
              <div className="card-body" style={{ display: 'flex', gap: 18, flexWrap: 'wrap', alignItems: 'center' }}>
                <StatusTag status={module.status} />
                <span className="muted small">
                  Dashboard permission: <strong>{data.required_permission}</strong>
                </span>
                <span className="muted small">
                  Generated {formatDateTime(data.generated_at)}
                </span>
              </div>
            </section>

            {module.status === 'Planned' && (
              <Alert tone="info" icon="info">
                This module is <strong>planned</strong>, not delivered. The dashboard reserves the
                module boundary and lists the scope that will be implemented, so no planned
                capability is presented as available.
              </Alert>
            )}

            {data.kpis?.length > 0 && (
              <section className="kpi-grid" aria-label="Module KPIs">
                {data.kpis.map((kpi) => (
                  <KpiCard key={kpi.label} label={kpi.label} value={kpi.value} context={kpi.context} />
                ))}
              </section>
            )}

            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))',
                gap: 16,
              }}
            >
              {data.breakdown?.length > 0 && (
                <section className="card">
                  <div className="card-head">
                    <div>
                      <h2 className="card-title">Status breakdown</h2>
                      <p className="card-subtitle">Current distribution in this module.</p>
                    </div>
                  </div>
                  <div className="card-body">
                    <div className="breakdown">
                      {data.breakdown.map((item) => (
                        <div className="breakdown-row" key={item.label}>
                          <span className="breakdown-label">{item.label}</span>
                          <div className="breakdown-track">
                            <div
                              className="breakdown-bar"
                              style={{ width: `${Math.round((item.value / maxBreakdown) * 100)}%` }}
                            />
                          </div>
                          <span className="breakdown-value">{item.value}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </section>
              )}

              {data.planned_items?.length > 0 && (
                <section className="card">
                  <div className="card-head">
                    <div>
                      <h2 className="card-title">Planned scope</h2>
                      <p className="card-subtitle">What this module will deliver.</p>
                    </div>
                  </div>
                  <div className="card-body">
                    <ul className="list-plain">
                      {data.planned_items.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </div>
                </section>
              )}

              {data.quick_links?.length > 0 && (
                <section className="card">
                  <div className="card-head">
                    <div>
                      <h2 className="card-title">Quick links</h2>
                      <p className="card-subtitle">Available pages in this module.</p>
                    </div>
                  </div>
                  <div className="card-body">
                    <div className="quick-links">
                      {data.quick_links.map((link) => (
                        <Link key={link.path} to={link.path} className="quick-link">
                          <span>{link.label}</span>
                          <Icon name="chevronRight" size={15} />
                        </Link>
                      ))}
                    </div>
                  </div>
                </section>
              )}
            </div>

            {data.recent_activity?.length > 0 && (
              <section className="card">
                <div className="card-head">
                  <div>
                    <h2 className="card-title">Recent module activity</h2>
                    <p className="card-subtitle">Audited actions related to this module.</p>
                  </div>
                </div>
                <div className="card-body flush">
                  <div className="table-wrap">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>Timestamp</th>
                          <th>Actor</th>
                          <th>Action</th>
                          <th>Entity</th>
                          <th>Outcome</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.recent_activity.map((entry) => (
                          <tr key={entry.id}>
                            <td className="nowrap tnum">{formatDateTime(entry.created_at)}</td>
                            <td>{entry.actor_username || 'system'}</td>
                            <td className="cell-primary">{entry.action}</td>
                            <td>{entry.entity_label || entry.entity_type || '—'}</td>
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
            )}
          </>
        )
      )}
    </div>
  )
}
