import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { listOperationTypes } from '../api/operationsApi'
import Icon from '../components/common/Icon'
import { Alert, KpiCard, Loading, PageHead, StatusTag } from '../components/common/Ui'
import { usePermissions } from '../hooks/usePermissions'

const SIGN_TONE = {
  SET: 'info',
  IN: 'success',
  OUT: 'warning',
  NEUTRAL: 'neutral',
}

const SIGN_HINT = {
  SET: 'Overrides the stock balance with the measured quantity.',
  IN: 'Adds the quantity to the stock balance.',
  OUT: 'Subtracts the quantity from the stock balance.',
  NEUTRAL: 'Accounted in the register; does not override or change the stock balance.',
}

function SignTag({ sign }) {
  return <StatusTag status={sign} tone={SIGN_TONE[sign] || 'neutral'} />
}

/**
 * Configurations > Operation Types. Read-only: the six operation types, their
 * fixed asset type, the eight categories and their stock sign. These are hard
 * coded server-side (no create, edit or delete) so the stock logic cannot be
 * changed by configuration.
 */
export default function OperationTypes() {
  const { isAdmin, hasPermission } = usePermissions()
  const canOpenMaster = isAdmin || hasPermission('operations:read')

  const [data, setData] = useState({ items: [], categories: [], signs: [] })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setData(await listOperationTypes())
    } catch (loadError) {
      setError(loadError.message || 'Unable to load operation types')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const activeOperations = (data.items || []).reduce(
    (sum, item) => sum + (item.active_operation_count || 0),
    0,
  )

  return (
    <div className="page">
      <PageHead
        eyebrow="CONFIGURATIONS / OPERATION TYPES"
        title="Operation Types"
        description="The fixed operation types, the asset type each one is recorded against, and the operation categories with their stock signs. These are built into HCA and cannot be edited, so the stock logic stays consistent."
        actions={
          <button type="button" className="btn btn-secondary" onClick={load} disabled={loading}>
            <Icon name="refresh" size={15} /> Refresh
          </button>
        }
      />
      {error && <Alert tone="danger">{error}</Alert>}

      {loading ? (
        <Loading label="Loading operation types…" />
      ) : (
        <>
          <div className="kpi-grid">
            <KpiCard label="Operation types" value={data.total || data.items.length} context="Fixed catalogue" />
            <KpiCard label="Categories" value={data.categories.length} context="Fixed list" />
            <KpiCard label="Active operations" value={activeOperations} context="Across all locations" />
          </div>

          <section className="card" style={{ marginTop: 16 }}>
            <div className="card-head">
              <h2 className="card-title">Operation types</h2>
              <p className="muted small">Each type is recorded against exactly one asset type. A prime mover has no operation of its own; its tanker trailer carries the tanker operations.</p>
            </div>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Operation type</th>
                    <th>Code</th>
                    <th>Asset type</th>
                    <th>Description</th>
                    <th>Operations</th>
                    <th aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((item) => (
                    <tr key={item.code}>
                      <td className="cell-primary">{item.name}</td>
                      <td className="cell-mono">{item.code}</td>
                      <td>{item.asset_type_name}</td>
                      <td style={{ whiteSpace: 'normal' }}>{item.description}</td>
                      <td className="nowrap">
                        {item.active_operation_count} active / {item.operation_count} total
                      </td>
                      <td>
                        {canOpenMaster && (
                          <Link to="/operations" className="btn btn-ghost btn-compact">
                            <Icon name="arrowRight" size={14} /> Operation Master
                          </Link>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="card" style={{ marginTop: 16 }}>
            <div className="card-head">
              <h2 className="card-title">Operation categories and stock signs</h2>
              <p className="muted small">The sign is set by the category and cannot be chosen separately. It decides how an operation changes the stock balance.</p>
            </div>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Category</th>
                    <th>Code</th>
                    <th>Stock sign</th>
                    <th>Meaning</th>
                    <th>Description</th>
                  </tr>
                </thead>
                <tbody>
                  {data.categories.map((category) => (
                    <tr key={category.code}>
                      <td className="cell-primary">{category.label}</td>
                      <td className="cell-mono">{category.code}</td>
                      <td>
                        <SignTag sign={category.sign} />
                      </td>
                      <td>{SIGN_HINT[category.sign]}</td>
                      <td style={{ whiteSpace: 'normal' }}>{category.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="card" style={{ marginTop: 16 }}>
            <div className="card-head">
              <h2 className="card-title">Stock signs</h2>
            </div>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Sign</th>
                    <th>Label</th>
                    <th>Meaning</th>
                  </tr>
                </thead>
                <tbody>
                  {data.signs.map((sign) => (
                    <tr key={sign.code}>
                      <td>
                        <SignTag sign={sign.code} />
                      </td>
                      <td>{sign.label}</td>
                      <td>{sign.meaning}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  )
}
