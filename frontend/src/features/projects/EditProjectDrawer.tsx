import { useId, useState } from 'react'
import { useAuth } from '../../auth/AuthContext'
import { Button } from '../../components/Button'
import { ConfirmModal } from '../../components/ConfirmModal'
import { Drawer } from '../../components/Drawer'
import { SelectField, TextField } from '../../components/Field'
import { SectionHeading } from '../../components/Card'
import { SkeletonRows } from '../../components/Skeleton'
import type { ProjectOut } from '../../types/api'
import { useSetProjectAiOverride } from '../ai/api'
import { useUsers } from '../users/api'
import { LOCATION_ROLES, MEMBER_ROLES, USER_DIRECTORY_ROLES } from './projectRoles'
import { useAddProjectMember, useProjectMembers, useRemoveProjectMember, useUpdateProjectLocation } from './api'

const inputClass =
  'mt-0.5 block rounded-control border border-outline px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand text-ink'

function LocationForm({ project }: { project: ProjectOut }) {
  const { hasRole } = useAuth()
  const canWrite = hasRole(...LOCATION_ROLES)
  const [emirate, setEmirate] = useState(project.emirate ?? '')
  const [area, setArea] = useState(project.area ?? '')
  const [latitude, setLatitude] = useState(project.latitude?.toString() ?? '')
  const [longitude, setLongitude] = useState(project.longitude?.toString() ?? '')
  const updateLocation = useUpdateProjectLocation(project.id)

  if (!canWrite) {
    return (
      <p className="text-sm text-muted">
        {[project.emirate, project.area].filter(Boolean).join(' · ') || 'No location set.'} Only a BD director or the
        managing director can change it.
      </p>
    )
  }

  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault()
        updateLocation.mutate({
          emirate: emirate || null,
          area: area || null,
          latitude: latitude ? Number(latitude) : null,
          longitude: longitude ? Number(longitude) : null,
        })
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
      <Button type="submit" loading={updateLocation.isPending}>
        Save location
      </Button>
      {updateLocation.isSuccess && (
        <p role="status" className="w-full text-sm text-success">
          Location saved
        </p>
      )}
      {updateLocation.isError && (
        <p role="alert" className="w-full text-sm text-danger">
          {updateLocation.error.message}
        </p>
      )}
    </form>
  )
}

// The project payload does not always carry external_ai_override, so this is
// driven by local state (undefined on the payload is treated as null).
function AiOverrideSection({ projectId, initial }: { projectId: string; initial: boolean | null }) {
  const { hasRole } = useAuth()
  const [override, setOverride] = useState<boolean | null>(initial)
  const setAiOverride = useSetProjectAiOverride(projectId)
  const checkboxId = useId()

  if (!hasRole(...LOCATION_ROLES)) return null

  return (
    <div>
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
    <div>
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
              {
                onSuccess: () => {
                  setSelectedUserId('')
                  setProjectRole('')
                },
              },
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
          <TextField label="Project role (optional)" value={projectRole} onChange={(e) => setProjectRole(e.target.value)} />
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
    </div>
  )
}

// "Edit project": everything the old Overview tab held (location, external-AI opt-out, members) in one drawer.
export function EditProjectDrawer({ project, open, onClose }: { project: ProjectOut; open: boolean; onClose: () => void }) {
  const { hasRole } = useAuth()
  return (
    <Drawer open={open} title="Edit project" onClose={onClose}>
      <div className="space-y-6">
        <section aria-label="Location">
          <SectionHeading>Location</SectionHeading>
          <LocationForm project={project} />
        </section>
        {hasRole(...LOCATION_ROLES) && (
          <section aria-label="External AI">
            <SectionHeading>External AI</SectionHeading>
            <AiOverrideSection projectId={project.id} initial={project.external_ai_override ?? null} />
          </section>
        )}
        <section aria-label="Members">
          <SectionHeading>Members</SectionHeading>
          <MembersSection projectId={project.id} />
        </section>
      </div>
    </Drawer>
  )
}
