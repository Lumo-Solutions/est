import { useState } from 'react'
import { Link, Navigate, useLocation, useParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { Badge } from '../components/Badge'
import { Button } from '../components/Button'
import { PageTitle } from '../components/PageTitle'
import { SkeletonRows } from '../components/Skeleton'
import { EditProjectDrawer } from '../features/projects/EditProjectDrawer'
import { USER_DIRECTORY_ROLES } from '../features/projects/projectRoles'
import { useProject, useProjectMembers } from '../features/projects/api'
import { ProjectDocuments } from '../features/tenderIntake/ProjectDocuments'
import { useUsers } from '../features/users/api'
import type { ProjectOut } from '../types/api'

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="truncate text-sm text-ink">{children}</dd>
    </div>
  )
}

// Who is on the project, as compact as the page header allows: names when the directory is readable for the
// signed-in role, otherwise just the count.
function MemberFact({ projectId }: { projectId: string }) {
  const { hasRole } = useAuth()
  const { data: members } = useProjectMembers(projectId)
  const { data: users } = useUsers({ enabled: hasRole(...USER_DIRECTORY_ROLES) })
  if (!members) return <>...</>
  if (members.length === 0) return <>No members yet</>
  const names = members.map((m) => users?.find((u) => u.id === m.user_id)?.username).filter(Boolean) as string[]
  if (names.length === 0) return <>{members.length} {members.length === 1 ? 'member' : 'members'}</>
  const shown = names.slice(0, 3).join(', ')
  return <>{names.length > 3 ? `${shown} +${names.length - 3}` : shown}</>
}

function ProjectHeader({ project, onEdit }: { project: ProjectOut; onEdit: () => void }) {
  const location = [project.emirate, project.area].filter(Boolean).join(' · ')
  return (
    <header className="mt-2 rounded-card bg-white p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <PageTitle>
            {project.code} -- {project.name}
          </PageTitle>
          <div className="mt-1 flex items-center gap-2 text-sm text-muted">
            <Badge tone="neutral">{project.status}</Badge>
            <span>{project.base_currency}</span>
          </div>
        </div>
        <Button variant="secondary" onClick={onEdit}>
          Edit project
        </Button>
      </div>
      <dl className="mt-4 grid grid-cols-2 gap-4 md:grid-cols-4">
        <Fact label="Client">{project.client_name ?? 'Not set'}</Fact>
        <Fact label="Tender ref">{project.tender_ref ?? 'Not set'}</Fact>
        <Fact label="Location">{location || 'Not set'}</Fact>
        <Fact label="Members">
          <MemberFact projectId={project.id} />
        </Fact>
      </dl>
    </header>
  )
}

// One page per project: the header, then everything about its tender documents. (It used to be an Overview tab
// and a Tender documents tab; an old ?tab= URL lands here and is cleaned up.)
export function ProjectDetailPage() {
  const { projectId } = useParams()
  const { pathname, search } = useLocation()
  const { data: project, isLoading, isError, error, refetch } = useProject(projectId)
  const [editing, setEditing] = useState(false)

  const backLink = (
    <Link
      to="/"
      className="rounded text-sm text-muted hover:text-ink hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
    >
      ← Projects
    </Link>
  )

  if (new URLSearchParams(search).has('tab')) return <Navigate to={pathname} replace />

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
      <ProjectHeader project={project} onEdit={() => setEditing(true)} />
      <ProjectDocuments projectId={project.id} />
      <EditProjectDrawer project={project} open={editing} onClose={() => setEditing(false)} />
    </div>
  )
}
