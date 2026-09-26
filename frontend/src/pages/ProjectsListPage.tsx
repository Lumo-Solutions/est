import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { useCreateProject, useProjects } from '../features/projects/api'
import { Role } from '../lib/roles'

const CREATE_ROLES = [Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR]

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
          className="rounded border border-slate-300 px-2 py-1 text-sm"
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
          className="rounded border border-slate-300 px-2 py-1 text-sm"
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
          className="rounded border border-slate-300 px-2 py-1 text-sm"
        />
      </div>
      <button
        type="submit"
        disabled={createProject.isPending}
        className="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
      >
        Create project
      </button>
      {createProject.isError && (
        <span className="text-sm text-red-600">{createProject.error.message}</span>
      )}
    </form>
  )
}

export function ProjectsListPage() {
  const { hasRole } = useAuth()
  const { data: projects, isLoading, isError, error } = useProjects()
  const [showForm, setShowForm] = useState(false)

  return (
    <div className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold text-slate-800">Projects</h1>
        {hasRole(...CREATE_ROLES) && (
          <button
            type="button"
            onClick={() => setShowForm((v) => !v)}
            className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
          >
            {showForm ? 'Cancel' : 'New project'}
          </button>
        )}
      </div>
      {showForm && <NewProjectForm onDone={() => setShowForm(false)} />}
      {isLoading && <p className="text-slate-500">Loading...</p>}
      {isError && <p className="text-red-600">{error.message}</p>}
      {projects && (
        <table className="w-full text-left text-sm">
          <thead className="border-b border-slate-200 text-slate-500">
            <tr>
              <th className="py-2">Code</th>
              <th>Name</th>
              <th>Client</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {projects.map((p) => (
              <tr key={p.id} className="border-b border-slate-100 hover:bg-slate-50">
                <td className="py-2">
                  <Link to={`/projects/${p.id}`} className="text-slate-800 hover:underline">
                    {p.code}
                  </Link>
                </td>
                <td>{p.name}</td>
                <td>{p.client_name ?? '--'}</td>
                <td>{p.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
