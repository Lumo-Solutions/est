import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { Badge, type BadgeTone } from '../components/Badge'
import { Button } from '../components/Button'
import { TextField } from '../components/Field'
import { Pagination } from '../components/Pagination'
import { SkeletonRows } from '../components/Skeleton'
import { Table, TableCard, Td, Th } from '../components/Table'
import { useCreateProject, useProjectsPage } from '../features/projects/api'
import { Role } from '../lib/roles'
import { PageTitle } from '../components/PageTitle'

// Mirrors backend/app/api/v1/routes/projects.py's _CREATE_ROLES (lead_estimator
// joined bd/md with migration 0029).
const CREATE_ROLES = [Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR, Role.LEAD_ESTIMATOR]
const PAGE_SIZE = 20

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

function NewProjectForm({ onDone }: { onDone: (projectId: string) => void }) {
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [clientName, setClientName] = useState('')
  const createProject = useCreateProject()

  return (
    <form
      className="mb-6 flex flex-wrap items-end gap-4 rounded-card bg-white p-6"
      onSubmit={(e) => {
        e.preventDefault()
        createProject.mutate(
          { code, name, client_name: clientName || null },
          { onSuccess: (created) => onDone(created.id) },
        )
      }}
    >
      <TextField label="Code" required value={code} onChange={(e) => setCode(e.target.value)} />
      <TextField label="Name" required value={name} onChange={(e) => setName(e.target.value)} />
      <TextField label="Client" value={clientName} onChange={(e) => setClientName(e.target.value)} />
      <Button type="submit" loading={createProject.isPending}>
        Create project
      </Button>
      {createProject.isError && (
        <span role="alert" className="text-sm text-red-700">
          {createProject.error.message}
        </span>
      )}
    </form>
  )
}

export function ProjectsListPage() {
  const { hasRole } = useAuth()
  const [page, setPage] = useState(1)
  const offset = (page - 1) * PAGE_SIZE
  const { data, isLoading, isError, error } = useProjectsPage({ limit: PAGE_SIZE, offset })
  const projects = data?.items
  const [showForm, setShowForm] = useState(false)
  const navigate = useNavigate()
  const canCreate = hasRole(...CREATE_ROLES)
  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1

  return (
    <div className="px-6 py-6 xl:px-10">
      <div className="mb-6 flex items-center justify-between">
        <PageTitle>Projects</PageTitle>
        {canCreate && (
          <Button variant="secondary" onClick={() => setShowForm((v) => !v)}>
            {showForm ? 'Cancel' : 'New project'}
          </Button>
        )}
      </div>
      {showForm && (
        <NewProjectForm
          onDone={(id) => {
            setShowForm(false)
            navigate(`/projects/${id}`)
          }}
        />
      )}
      {isLoading && <SkeletonRows count={5} />}
      {isError && (
        <p role="alert" className="text-red-700">
          {error.message}
        </p>
      )}
      {projects && projects.length === 0 && (
        <div className="rounded-card bg-white p-10 text-center">
          <p className="text-base text-muted">No projects yet.</p>
          {canCreate && !showForm && (
            <Button className="mt-4" onClick={() => setShowForm(true)}>
              New project
            </Button>
          )}
        </div>
      )}
      {projects && projects.length > 0 && (
        <TableCard>
          <Table density="comfortable">
            <thead>
              <tr>
                <Th>Code</Th>
                <Th>Name</Th>
                <Th>Client</Th>
                <Th>Status</Th>
              </tr>
            </thead>
            <tbody>
              {projects.map((p) => (
                <tr key={p.id} className="hover:bg-canvas">
                  <Td>
                    <Link
                      to={`/projects/${p.id}`}
                      className="rounded font-medium text-brand hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
                    >
                      {p.code}
                    </Link>
                  </Td>
                  <Td>{p.name}</Td>
                  <Td>{p.client_name ?? '--'}</Td>
                  <Td>
                    <Badge tone={STATUS_TONE[p.status] ?? 'neutral'}>{p.status}</Badge>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </TableCard>
      )}
      {data && data.total > 0 && (
        <div className="mt-6 flex flex-wrap items-center justify-between gap-4">
          <p className="text-sm text-muted">
            Page {page} of {totalPages} ({data.total} project{data.total === 1 ? '' : 's'})
          </p>
          <Pagination page={page} pageCount={totalPages} onPageChange={setPage} />
        </div>
      )}
    </div>
  )
}
