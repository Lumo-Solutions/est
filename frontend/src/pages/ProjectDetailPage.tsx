import { useId, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { Badge, type BadgeTone } from '../components/Badge'
import { Button } from '../components/Button'
import { Card, SectionHeading } from '../components/Card'
import { ConfirmModal } from '../components/ConfirmModal'
import { SelectField, TextField } from '../components/Field'
import { SkeletonRows } from '../components/Skeleton'
import { TabBar } from '../components/TabBar'
import { useSetProjectAiOverride } from '../features/ai/api'
import { DrawingUpload } from '../features/drawings/DrawingUpload'
import { useDrawings } from '../features/drawings/api'
import {
  useAddProjectMember,
  useProject,
  useProjectMembers,
  useRemoveProjectMember,
  useUpdateProjectLocation,
} from '../features/projects/api'
import { TenderDocumentsTab } from '../features/tenderIntake/TenderDocumentsTab'
import { useUsers } from '../features/users/api'
import { Role } from '../lib/roles'
import { PageTitle } from '../components/PageTitle'

// docs/ui-design-system.md section 4.8 -- drawing DrawingStatus's own
// vocabulary mapped to the shared Badge's tones.
const DRAWING_STATUS_TONE: Record<string, BadgeTone> = {
  ready: 'success',
  failed: 'danger',
  partial: 'warning',
  needs_conversion: 'warning',
  converting: 'info',
}

// Mirrors backend/app/api/v1/routes/projects.py's _LOCATION_ROLES (project
// creation and member-adding have their own, wider lists there).
const LOCATION_ROLES = [Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR]
const MEMBER_ROLES = [Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR, Role.LEAD_ESTIMATOR]
// GET /users is restricted server-side (backend/app/api/v1/routes/users.py
// _READ_ROLES). Requesting it as an estimator was a guaranteed 403 -- a
// console error on every project page, previously masked by e2e timing.
const USER_DIRECTORY_ROLES = [
  Role.LEAD_ESTIMATOR,
  Role.PROCUREMENT_HEAD,
  Role.BD_DIRECTOR,
  Role.MANAGING_DIRECTOR,
]

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
    'mt-0.5 block rounded-control border border-outline px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand text-ink'

  return (
    <form
      className="mt-2 flex flex-wrap items-end gap-2 rounded-card p-5 bg-white"
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
      <label className="text-xs text-muted">
        Emirate
        <input value={emirate} onChange={(e) => setEmirate(e.target.value)} className={inputClass} />
      </label>
      <label className="text-xs text-muted">
        Area
        <input value={area} onChange={(e) => setArea(e.target.value)} className={inputClass} />
      </label>
      <label className="text-xs text-muted">
        Latitude
        <input value={latitude} onChange={(e) => setLatitude(e.target.value)} className={`${inputClass} w-24`} />
      </label>
      <label className="text-xs text-muted">
        Longitude
        <input value={longitude} onChange={(e) => setLongitude(e.target.value)} className={`${inputClass} w-24`} />
      </label>
      <button
        type="submit"
        disabled={updateLocation.isPending}
        className="rounded-control bg-brand px-4 py-1.5 text-sm font-medium text-white transition-colors duration-150 hover:bg-brand-hover disabled:opacity-50"
      >
        Save
      </button>
      <button
        type="button"
        onClick={() => setEditing(false)}
        className="rounded px-2 py-1.5 text-sm text-muted hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
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

// The project payload does not carry external_ai_override yet, so this is
// driven by local state (undefined on the payload is treated as null).
function AiOverrideSection({ projectId, initial }: { projectId: string; initial: boolean | null }) {
  const { hasRole } = useAuth()
  const [override, setOverride] = useState<boolean | null>(initial)
  const setAiOverride = useSetProjectAiOverride(projectId)
  const checkboxId = useId()

  if (!hasRole(...LOCATION_ROLES)) return null

  return (
    <div className="mt-2">
      <label htmlFor={checkboxId} className="flex items-center gap-2 text-sm text-slate-600">
        <input
          id={checkboxId}
          type="checkbox"
          checked={override === false}
          disabled={setAiOverride.isPending}
          onChange={(e) => {
            const next = e.target.checked ? false : null
            const previous = override
            setOverride(next)
            setAiOverride.mutate(next, { onError: () => setOverride(previous) })
          }}
          className="h-4 w-4 rounded border-slate-300 text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
        />
        Keep this project off external AI
      </label>
      {setAiOverride.isError && (
        <p role="alert" className="mt-1 text-sm text-danger">
          {setAiOverride.error.message}
        </p>
      )}
    </div>
  )
}

function MembersSection({ projectId }: { projectId: string }) {
  const { hasRole } = useAuth()
  const canWrite = hasRole(...MEMBER_ROLES)
  const { data: members, isLoading, isError, error } = useProjectMembers(projectId)
  const { data: users } = useUsers({ enabled: hasRole(...USER_DIRECTORY_ROLES) })
  const [selectedUserId, setSelectedUserId] = useState('')
  const [projectRole, setProjectRole] = useState('')
  const addMember = useAddProjectMember(projectId)
  const removeMember = useRemoveProjectMember(projectId)
  const [memberToRemove, setMemberToRemove] = useState<string | null>(null)

  const usernameFor = (userId: string) => users?.find((u) => u.id === userId)?.username ?? userId

  return (
    <Card className="mt-6">
      <SectionHeading>Members</SectionHeading>
      {isLoading && <SkeletonRows count={2} />}
      {isError && (
        <p role="alert" className="text-sm text-danger">
          {error.message}
        </p>
      )}
      {members && members.length === 0 && <p className="text-sm text-muted">No members added yet.</p>}
      {members && members.length > 0 && (
        <ul className="divide-y divide-row-rule">
          {members.map((m) => (
            <li key={m.user_id} className="flex items-center gap-3 py-3 text-base text-ink">
              <span>
                {usernameFor(m.user_id)}
                {m.project_role && <span className="ml-2 text-xs text-muted">({m.project_role})</span>}
              </span>
              {canWrite && (
                <button
                  type="button"
                  onClick={() => setMemberToRemove(m.user_id)}
                  disabled={removeMember.isPending}
                  aria-label={`Remove ${usernameFor(m.user_id)}`}
                  className="rounded text-xs text-danger hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1 disabled:opacity-50"
                >
                  Remove
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {removeMember.isError && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {removeMember.error.message}
        </p>
      )}
      <ConfirmModal
        open={memberToRemove !== null}
        title="Remove member?"
        message={`${memberToRemove ? usernameFor(memberToRemove) : ''} will lose access to this project.`}
        confirmLabel="Remove"
        onCancel={() => setMemberToRemove(null)}
        onConfirm={() => {
          if (memberToRemove) removeMember.mutate(memberToRemove)
          setMemberToRemove(null)
        }}
      />
      {canWrite && (
        <form
          className="mt-4 flex flex-wrap items-end gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            if (!selectedUserId) return
            addMember.mutate(
              { user_id: selectedUserId, project_role: projectRole || null },
              { onSuccess: () => { setSelectedUserId(''); setProjectRole('') } },
            )
          }}
        >
          <SelectField label="User" value={selectedUserId} onChange={(e) => setSelectedUserId(e.target.value)}>
            <option value="">-- Select a user --</option>
            {(users ?? []).map((u) => (
              <option key={u.id} value={u.id}>
                {u.username} {u.roles.length > 0 ? `(${u.roles.join(', ')})` : ''}
              </option>
            ))}
          </SelectField>
          <TextField
            label="Project role (optional)"
            value={projectRole}
            onChange={(e) => setProjectRole(e.target.value)}
          />
          <Button type="submit" disabled={!selectedUserId} loading={addMember.isPending}>
            Add member
          </Button>
          {addMember.isError && (
            <p role="alert" className="w-full text-sm text-danger">
              {addMember.error.message}
            </p>
          )}
        </form>
      )}
    </Card>
  )
}

export function ProjectDetailPage() {
  const { projectId } = useParams()
  const { data: project, isLoading, isError, error, refetch } = useProject(projectId)
  const { data: drawings } = useDrawings(projectId)
  const [searchParams, setSearchParams] = useSearchParams()
  const tab = searchParams.get('tab') === 'tender-documents' ? 'tender-documents' : 'overview'

  const backLink = (
    <Link
      to="/"
      className="rounded text-sm text-muted hover:text-ink hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
    >
      ← Projects
    </Link>
  )

  if (isLoading) {
    return (
      <div className="px-6 py-6 xl:px-10">
        {backLink}
        <div className="mt-4">
          <SkeletonRows count={4} />
        </div>
      </div>
    )
  }
  if (isError) {
    return (
      <div className="px-6 py-6 xl:px-10">
        {backLink}
        <p role="alert" className="mt-4 text-danger">
          {error.message}
        </p>
        <Button variant="secondary" size="sm" className="mt-2" onClick={() => refetch()}>
          Retry
        </Button>
      </div>
    )
  }
  if (!project) return null

  return (
    <div className="px-6 py-6 xl:px-10">
      {backLink}
      <PageTitle>
        {project.code} -- {project.name}
      </PageTitle>
      <p className="mt-1 text-sm text-muted">
        {project.client_name ?? 'No client set'} · {project.status} · {project.base_currency}
        {project.emirate ? ` · ${project.emirate}` : ''}
      </p>
      <div className="mt-4">
        <TabBar
          pattern="buttons"
          label="Project sections"
          idPrefix="project"
          value={tab}
          onChange={(id) => setSearchParams(id === 'overview' ? {} : { tab: id }, { replace: true })}
          tabs={[
            { id: 'overview', label: 'Overview' },
            { id: 'tender-documents', label: 'Tender documents' },
          ]}
        />
      </div>
      {tab === 'tender-documents' && <TenderDocumentsTab projectId={project.id} />}
      {tab === 'overview' && (
        <>
      <LocationSection project={project} />
      <AiOverrideSection
        projectId={project.id}
        initial={project.external_ai_override ?? null}
      />
      <MembersSection projectId={project.id} />

      <Card className="mt-6">
        <SectionHeading>Drawings</SectionHeading>
        <DrawingUpload projectId={project.id} />
        {drawings && drawings.length === 0 && <p className="mt-3 text-base text-muted">No drawings uploaded yet.</p>}
        {drawings && drawings.length > 0 && (
          <ul className="mt-3 divide-y divide-row-rule">
            {drawings.map((d) => (
              <li key={d.id} className="flex items-center justify-between py-3">
                <Link
                  to={`/projects/${project.id}/drawings/${d.id}`}
                  className="rounded text-base font-medium text-brand hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
                >
                  {d.original_filename}
                </Link>
                <div className="flex items-center gap-3 text-sm text-muted">
                  <span>{d.sheet_count ?? '?'} sheet(s)</span>
                  {d.kind === 'dwg' && <Badge tone="neutral">DWG</Badge>}
                  <Badge tone={DRAWING_STATUS_TONE[d.status] ?? 'neutral'}>{d.status.replace('_', ' ')}</Badge>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
        </>
      )}
    </div>
  )
}
