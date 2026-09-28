import { useId, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { Badge, type BadgeTone } from '../components/Badge'
import { SkeletonRows } from '../components/Skeleton'
import { DrawingUpload } from '../features/drawings/DrawingUpload'
import { useDrawings } from '../features/drawings/api'
import { useAddProjectMember, useProject, useProjectMembers, useUpdateProjectLocation } from '../features/projects/api'
import { useUsers } from '../features/users/api'
import { Role } from '../lib/roles'

// docs/ui-design-system.md section 4.8 -- drawing DrawingStatus's own
// vocabulary mapped to the shared Badge's tones.
const DRAWING_STATUS_TONE: Record<string, BadgeTone> = {
  ready: 'success',
  failed: 'danger',
  partial: 'warning',
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
        className="mt-2 rounded text-sm text-brand hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
      >
        Edit location
      </button>
    )
  }

  const inputClass =
    'mt-0.5 block rounded border border-slate-300 px-2 py-1.5 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand'

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
        <input value={emirate} onChange={(e) => setEmirate(e.target.value)} className={inputClass} />
      </label>
      <label className="text-xs text-slate-500">
        Area
        <input value={area} onChange={(e) => setArea(e.target.value)} className={inputClass} />
      </label>
      <label className="text-xs text-slate-500">
        Latitude
        <input value={latitude} onChange={(e) => setLatitude(e.target.value)} className={`${inputClass} w-24`} />
      </label>
      <label className="text-xs text-slate-500">
        Longitude
        <input value={longitude} onChange={(e) => setLongitude(e.target.value)} className={`${inputClass} w-24`} />
      </label>
      <button
        type="submit"
        disabled={updateLocation.isPending}
        className="rounded bg-brand px-3 py-1.5 text-sm font-medium text-white transition-colors duration-150 hover:bg-brand-hover disabled:opacity-50"
      >
        Save
      </button>
      <button
        type="button"
        onClick={() => setEditing(false)}
        className="rounded px-2 py-1.5 text-sm text-slate-500 hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
      >
        Cancel
      </button>
      {updateLocation.isError && (
        <p role="alert" className="w-full text-sm text-danger">
          {updateLocation.error.message}
        </p>
      )}
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
  const userSelectId = useId()
  const projectRoleId = useId()

  const usernameFor = (userId: string) => users?.find((u) => u.id === userId)?.username ?? userId

  return (
    <div className="mt-6">
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">Members</h2>
      {isLoading && <SkeletonRows count={2} />}
      {isError && (
        <p role="alert" className="text-sm text-danger">
          {error.message}
        </p>
      )}
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
          <div>
            <label htmlFor={userSelectId} className="block text-xs text-slate-500">
              User
            </label>
            <select
              id={userSelectId}
              value={selectedUserId}
              onChange={(e) => setSelectedUserId(e.target.value)}
              className="mt-0.5 rounded border border-slate-300 px-2 py-1.5 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
            >
              <option value="">-- Select a user --</option>
              {(users ?? []).map((u) => (
                <option key={u.id} value={u.id}>
                  {u.username} {u.roles.length > 0 ? `(${u.roles.join(', ')})` : ''}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor={projectRoleId} className="block text-xs text-slate-500">
              Project role (optional)
            </label>
            <input
              id={projectRoleId}
              value={projectRole}
              onChange={(e) => setProjectRole(e.target.value)}
              className="mt-0.5 rounded border border-slate-300 px-2 py-1.5 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
            />
          </div>
          <button
            type="submit"
            disabled={!selectedUserId || addMember.isPending}
            className="rounded bg-brand px-3 py-1.5 text-sm font-medium text-white transition-colors duration-150 hover:bg-brand-hover disabled:opacity-50"
          >
            Add member
          </button>
          {addMember.isError && (
            <p role="alert" className="w-full text-sm text-danger">
              {addMember.error.message}
            </p>
          )}
        </form>
      )}
    </div>
  )
}

export function ProjectDetailPage() {
  const { projectId } = useParams()
  const { data: project, isLoading, isError, error, refetch } = useProject(projectId)
  const { data: drawings } = useDrawings(projectId)

  const backLink = (
    <Link
      to="/"
      className="rounded text-sm text-slate-500 hover:text-slate-800 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
    >
      ← Projects
    </Link>
  )

  if (isLoading) {
    return (
      <div className="p-6">
        {backLink}
        <div className="mt-4">
          <SkeletonRows count={4} />
        </div>
      </div>
    )
  }
  if (isError) {
    return (
      <div className="p-6">
        {backLink}
        <p role="alert" className="mt-4 text-danger">
          {error.message}
        </p>
        <button
          type="button"
          onClick={() => refetch()}
          className="mt-2 rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 transition-colors duration-150 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
        >
          Retry
        </button>
      </div>
    )
  }
  if (!project) return null

  return (
    <div className="p-6">
      {backLink}
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
              <Link
                to={`/projects/${project.id}/drawings/${d.id}`}
                className="rounded text-sm text-slate-800 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
              >
                {d.original_filename}
              </Link>
              <div className="flex items-center gap-3 text-xs text-slate-500">
                <span>{d.sheet_count ?? '?'} sheet(s)</span>
                <Badge tone={DRAWING_STATUS_TONE[d.status] ?? 'neutral'}>{d.status}</Badge>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
