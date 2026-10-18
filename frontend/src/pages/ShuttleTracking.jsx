import { useSearchParams } from 'react-router-dom'
import { PageHead } from '../components/common/Ui'
import { VoyageDetail, VoyageList } from '../components/operationTracking/VoyageTracking'
import '../styles/operation-entry.css'
import '../styles/operation-tracking.css'

/**
 * OTMS Shuttle Tracking: voyages per location + shuttle vessel + shuttle
 * number. Receipts are loading / STS-in / top-up, discharge is unloading;
 * quantities are |net stock| + |net water| and are never netted.
 */
export default function ShuttleTracking() {
  const [params, setParams] = useSearchParams()
  const voyage = params.get('voyage')
  return (
    <div className="page operation-tracking">
      <PageHead
        eyebrow="OPERATION TRACKING / SHUTTLE TRACKING"
        title="Shuttle Tracking"
        description="Shuttle voyages built from Approved shuttle tickets: net receipt, net discharge and STS transfers per shuttle number, with close / reopen and the voyage MTR."
      />
      {voyage ? (
        <VoyageDetail kind="shuttle" voyageId={voyage} onBack={() => setParams({})} />
      ) : (
        <VoyageList kind="shuttle" onOpen={(id) => setParams({ voyage: String(id) })} />
      )}
    </div>
  )
}
