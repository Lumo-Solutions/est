import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { DrawingUpload } from '../features/drawings/DrawingUpload'
import { useDrawings } from '../features/drawings/api'
import { useAddProjectMember, useProject, useProjectMembers, useUpdateProjectLocation } from '../features/projects/api'
import { useUsers } from '../features/users/api'
import { Role } from '../lib/roles'

const STATUS_STYLES: Record<string, string> = {
  ready: 'bg-green-100 text-green-800',
  failed: 'bg-red-100 text-red-800',
  partial: 'bg-amber-100 text-amber-800',
}

function StatusBadge({ status }: { status: string }) {
  const style = STATUS_STYLES[status] ?? 'bg-slate-100 text-slate-600'
  return <span className={`rounded px-2 py-0.5 text-xs font-medium ${style}`}>{status}</span>
}

// Mirrors backend/app/api/v1/routes/projects.py's _CREATE_ROLES -- location
// editing and member-adding both key off this (member-adding additionally
// allows lead_estimator, handled separately below).
const LOCATION_ROLES = [Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR]
const MEMBER_ROLES = [Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR, Role.LEAD_ESTIMATOR]

function LocationSection({ project }: { project: { id: string; emirate: string | null; area: string | null; latitude: number | null; longitude: number | null } }) {
  const { hasRole } = useAuth()
  const canWrite = hasRole(...LOCATION_ROLES)
  const [editing, setEditing] = useState(false)
  const [emirate, setEmirate] = useState(project.emirate ?? '')
  const [area, setArea] = useState(project.area ?? '')
  const [latitude, setLatitude] = useState(project.latitude?.toString() ?? '')
  const [longitude, setLongitude] = useState(project.longitude?.toString() ?? '')
  const updateLocation = useUpdateProjectLocation(project.id)

  if (!canWrite) return null

  if (!editing) {
    return (
      <button
        type="button"
        onClick={() => setEditing(true)}
        className="mt-2 text-sm text-slate-600 underline"
      >
        Edit location
      </button>
    )
  }

  return (
    <form
      className="mt-2 flex flex-wrap items-end gap-2 rounded border border-slate-200 p-3"
      onSubmit={(e) => {
        e.preventDefault()
        updateLocation.mutate(
          {
            emirate: emirate || null,
            area: area || null,
            latitude: latitude ? Number(latitude) : null,
            longitude: longitude ? Number(longitude) : null,
          },
          { onSuccess: () => setEditing(false) },
        )
      }}
    >
      <label className="text-xs text-slate-500">
        Emirate
        <input value={emirate} onChange={(e) => setEmirate(e.target.value)} className="mt-0.5 block rounded border border-slate-300 px-2 py-1 text-sm" />
      </label>
      <label className="text-xs text-slate-500">
        Area
        <input value={area} onChange={(e) => setArea(e.target.value)} className="mt-0.5 block rounded border border-slate-300 px-2 py-1 text-sm" />
      </label>
      <label className="text-xs text-slate-500">
        Latitude
        <input value={latitude} onChange={(e) => setLatitude(e.target.value)} className="mt-0.5 block w-24 rounded border border-slate-300 px-2 py-1 text-sm" />
      </label>
      <label className="text-xs text-slate-500">
        Longitude
        <input value={longitude} onChange={(e) => setLongitude(e.target.value)} className="mt-0.5 block w-24 rounded border border-slate-300 px-2 py-1 text-sm" />
      </label>
      <button type="submit" disabled={updateLocation.isPending} className="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50">
        Save
      </button>
      <button type="button" onClick={() => setEditing(false)} className="text-sm text-slate-500">
        Cancel
      </button>
      {updateLocation.isError && <p className="w-full text-sm text-red-600">{updateLocation.error.message}</p>}
    </form>
  )
}

function MembersSection({ projectId }: { projectId: string }) {
  const { hasRole } = useAuth()
  const canWrite = hasRole(...MEMBER_ROLES)
  const { data: members, isLoading, isError, error } = useProjectMembers(projectId)
  const { data: users } = useUsers()
  const [selectedUserId, setSelectedUserId] = useState('')
  const [projectRole, setProjectRole] = useState('')
  const addMember = useAddProjectMember(projectId)

  const usernameFor = (userId: string) => users?.find((u) => u.id === userId)?.username ?? userId

  return (
    <div className="mt-6">
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">Members</h2>
      {isLoading && <p className="text-sm text-slate-500">Loading...</p>}
      {isError && <p className="text-sm text-red-600">{error.message}</p>}
      {members && members.length === 0 && <p className="text-sm text-slate-500">No members added yet.</p>}
      {members && members.length > 0 && (
        <ul className="space-y-1">
          {members.map((m) => (
            <li key={m.user_id} className="text-sm text-slate-700">
              {usernameFor(m.user_id)}
              {m.project_role && <span className="ml-2 text-xs text-slate-500">({m.project_role})</span>}
            </li>
          ))}
        </ul>
      )}
      {canWrite && (
        <form
          className="mt-3 flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (!selectedUserId) return
            addMember.mutate(
              { user_id: selectedUserId, project_role: projectRole || null },
              { onSuccess: () => { setSelectedUserId(''); setProjectRole('') } },
            )
          }}
        >
          <select
            value={selectedUserId}
            onChange={(e) => setSelectedUserId(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1 text-sm"
          >
            <option value="">-- Select a user --</option>
            {(users ?? []).map((u) => (
              <option key={u.id} value={u.id}>
                {u.username} {u.roles.length > 0 ? `(${u.roles.join(', ')})` : ''}
              </option>
            ))}
          </select>
          <input
            placeholder="Project role (optional)"
            value={projectRole}
            onChange={(e) => setProjectRole(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1 text-sm"
          />
          <button type="submit" disabled={!selectedUserId || addMember.isPending} className="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50">
            Add member
          </button>
          {addMember.isError && <p className="w-full text-sm text-red-600">{addMember.error.message}</p>}
        </form>
      )}
    </div>
  )
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
      <LocationSection project={project} />
      <MembersSection projectId={project.id} />

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
