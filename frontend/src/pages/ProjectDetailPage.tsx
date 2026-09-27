import { Link, useParams } from 'react-router-dom'
import { DrawingUpload } from '../features/drawings/DrawingUpload'
import { useDrawings } from '../features/drawings/api'
import { useProject } from '../features/projects/api'

const STATUS_STYLES: Record<string, string> = {
  ready: 'bg-green-100 text-green-800',
  failed: 'bg-red-100 text-red-800',
  partial: 'bg-amber-100 text-amber-800',
}

function StatusBadge({ status }: { status: string }) {
  const style = STATUS_STYLES[status] ?? 'bg-slate-100 text-slate-600'
  return <span className={`rounded px-2 py-0.5 text-xs font-medium ${style}`}>{status}</span>
}

export function ProjectDetailPage() {
  const { projectId } = useParams()
  const { data: project, isLoading, isError, error, refetch } = useProject(projectId)
  const { data: drawings } = useDrawings(projectId)

  if (isLoading) return <p className="p-6 text-slate-500">Loading...</p>
  if (isError) {
    return (
      <div className="p-6">
        <Link to="/" className="text-sm text-slate-500 hover:text-slate-800 hover:underline">
          ← Projects
        </Link>
        <p className="mt-4 text-red-600">{error.message}</p>
        <button
          type="button"
          onClick={() => refetch()}
          className="mt-2 rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
        >
          Retry
        </button>
      </div>
    )
  }
  if (!project) return null

  return (
    <div className="p-6">
      <Link to="/" className="text-sm text-slate-500 hover:text-slate-800 hover:underline">
        ← Projects
      </Link>
      <h1 className="mt-2 text-xl font-semibold text-slate-800">
        {project.code} -- {project.name}
      </h1>
      <p className="mt-1 text-sm text-slate-500">
        {project.client_name ?? 'No client set'} · {project.status} · {project.base_currency}
        {project.emirate ? ` · ${project.emirate}` : ''}
      </p>

      <h2 className="mt-6 mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">Drawings</h2>
      <DrawingUpload projectId={project.id} />
      {drawings && drawings.length === 0 && <p className="text-sm text-slate-500">No drawings uploaded yet.</p>}
      {drawings && drawings.length > 0 && (
        <ul className="divide-y divide-slate-100">
          {drawings.map((d) => (
            <li key={d.id} className="flex items-center justify-between py-2">
              <Link to={`/projects/${project.id}/drawings/${d.id}`} className="text-sm text-slate-800 hover:underline">
                {d.original_filename}
              </Link>
              <div className="flex items-center gap-3 text-xs text-slate-500">
                <span>{d.sheet_count ?? '?'} sheet(s)</span>
                <StatusBadge status={d.status} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
