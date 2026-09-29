import { Link } from 'react-router-dom'
import { PageTitle } from '../components/PageTitle'

export function NotFoundPage() {
  return (
    <div className="px-6 py-6 xl:px-10">
      <PageTitle>Page not found</PageTitle>
      <p className="mt-2 text-sm text-muted">
        There's nothing here. Check the link, or go back to your projects.
      </p>
      <Link to="/" className="mt-4 inline-block text-sm text-ink hover:underline">
        ← Projects
      </Link>
    </div>
  )
}
