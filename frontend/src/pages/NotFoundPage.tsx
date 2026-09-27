import { Link } from 'react-router-dom'

export function NotFoundPage() {
  return (
    <div className="p-6">
      <h1 className="text-xl font-semibold text-slate-800">Page not found</h1>
      <p className="mt-2 text-sm text-slate-500">
        There's nothing here. Check the link, or go back to your projects.
      </p>
      <Link to="/" className="mt-4 inline-block text-sm text-slate-800 hover:underline">
        ← Projects
      </Link>
    </div>
  )
}
