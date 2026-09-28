import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { Badge, type BadgeTone } from '../components/Badge'
import { SkeletonRows } from '../components/Skeleton'
import { useCreateProject, useProjects } from '../features/projects/api'
import { Role } from '../lib/roles'

const CREATE_ROLES = [Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR]

// docs/ui-design-system.md section 4.8 -- ProjectStatus (backend/app/core/enums.py)
// mapped to the shared Badge's 4 semantic tones + neutral.
const STATUS_TONE: Record<string, BadgeTone> = {
  prospect: 'neutral',
  tendering: 'info',
  submitted: 'info',
  awarded: 'success',
  lost: 'danger',
  archived: 'neutral',
}

function NewProjectForm({ onDone }: { onDone: () => void }) {
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [clientName, setClientName] = useState('')
  const createProject = useCreateProject()

  return (
    <form
      className="mb-6 flex flex-wrap items-end gap-2 rounded border border-slate-200 p-4"
      onSubmit={(e) => {
        e.preventDefault()
        createProject.mutate(
          { code, name, client_name: clientName || null },
          { onSuccess: onDone },
        )
      }}
    >
      <div>
        <label className="block text-xs text-slate-500" htmlFor="code">
          Code
        </label>
        <input
          id="code"
          required
          value={code}
          onChange={(e) => setCode(e.target.value)}
          className="rounded border border-slate-300 px-2 py-1.5 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
        />
      </div>
      <div>
        <label className="block text-xs text-slate-500" htmlFor="name">
          Name
        </label>
        <input
          id="name"
          required
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="rounded border border-slate-300 px-2 py-1.5 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
        />
      </div>
      <div>
        <label className="block text-xs text-slate-500" htmlFor="client">
          Client
        </label>
        <input
          id="client"
          value={clientName}
          onChange={(e) => setClientName(e.target.value)}
          className="rounded border border-slate-300 px-2 py-1.5 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
        />
      </div>
      <button
        type="submit"
        disabled={createProject.isPending}
        className="rounded bg-brand px-3 py-1.5 text-sm font-medium text-white transition-colors duration-150 hover:bg-brand-hover disabled:opacity-50"
      >
        Create project
      </button>
      {createProject.isError && (
        <span role="alert" className="text-sm text-danger">
          {createProject.error.message}
        </span>
      )}
    </form>
  )
}

export function ProjectsListPage() {
  const { hasRole } = useAuth()
  const { data: projects, isLoading, isError, error } = useProjects()
  const [showForm, setShowForm] = useState(false)
  const canCreate = hasRole(...CREATE_ROLES)

  return (
    <div className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold text-slate-800">Projects</h1>
        {canCreate && (
          <button
            type="button"
            onClick={() => setShowForm((v) => !v)}
            className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 transition-colors duration-150 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
          >
            {showForm ? 'Cancel' : 'New project'}
          </button>
        )}
      </div>
      {showForm && <NewProjectForm onDone={() => setShowForm(false)} />}
      {isLoading && <SkeletonRows count={5} />}
      {isError && (
        <p role="alert" className="text-danger">
          {error.message}
        </p>
      )}
      {projects && projects.length === 0 && (
        <div className="rounded border border-slate-200 p-6 text-center">
          <p className="text-sm text-slate-500">No projects yet.</p>
          {canCreate && !showForm && (
            <button
              type="button"
              onClick={() => setShowForm(true)}
              className="mt-3 rounded bg-brand px-3 py-1.5 text-sm font-medium text-white transition-colors duration-150 hover:bg-brand-hover"
            >
              New project
            </button>
          )}
        </div>
      )}
      {projects && projects.length > 0 && (
        <table className="w-full text-left text-sm">
          <thead className="border-b border-slate-200 text-slate-500">
            <tr>
              <th className="py-2 font-medium">Code</th>
              <th className="font-medium">Name</th>
              <th className="font-medium">Client</th>
              <th className="font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {projects.map((p) => (
              <tr key={p.id} className="border-b border-slate-100 hover:bg-slate-50">
                <td className="py-2">
                  <Link
                    to={`/projects/${p.id}`}
                    className="text-slate-800 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
                  >
                    {p.code}
                  </Link>
                </td>
                <td>{p.name}</td>
                <td>{p.client_name ?? '--'}</td>
                <td>
                  <Badge tone={STATUS_TONE[p.status] ?? 'neutral'}>{p.status}</Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
