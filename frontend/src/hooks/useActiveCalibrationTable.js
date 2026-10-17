import { useMemo } from 'react'

// Only the selected asset's bounded, canonical chart is loaded by Operation Entry.
// The OTMS layout contract is preserved; no editable calibration template exists.
export function useActiveCalibrationTable({ assetCalibrationTables = [], assetCode }) {
  const table = useMemo(() => assetCalibrationTables.find(t => t.assetCode === assetCode && t.status === 'Active') || null, [assetCalibrationTables, assetCode])
  return { table, rows: table?.rows || [], loading: false, error: '' }
}
