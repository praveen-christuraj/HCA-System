import { Link } from 'react-router-dom'
import { PageHead } from '../components/common/Ui'

export default function NotFound() {
  return (
    <div className="page">
      <PageHead
        eyebrow="APPLICATION / NOT FOUND"
        title="Page not found"
        description="The page you requested does not exist or has moved."
        actions={
          <Link to="/" className="btn btn-primary">
            Back to dashboard
          </Link>
        }
      />
    </div>
  )
}
