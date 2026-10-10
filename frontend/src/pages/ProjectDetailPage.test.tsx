import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

let roles: string[] = ['lead_estimator']
vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ hasRole: (...r: string[]) => r.some((x) => roles.includes(x)) }),
}))

const project = {
  id: 'p1',
  code: 'AL-REEM-3',
  name: 'Al Reem Package 3',
  client_name: 'Reem Developments',
  status: 'active',
  tender_ref: 'T-2026-014',
  base_currency: 'AED',
  emirate: 'Abu Dhabi',
  area: 'Al Reem Island',
  latitude: null,
  longitude: null,
  external_ai_override: null,
  created_at: '2026-01-01T00:00:00Z',
}
let projectState: { data?: typeof project; isLoading: boolean; isError: boolean } = { data: project, isLoading: false, isError: false }
const members = [
  { user_id: 'u1', project_role: null },
  { user_id: 'u2', project_role: 'estimator' },
]
vi.mock('../features/projects/api', () => ({
  useProject: () => ({ ...projectState, error: new Error('boom'), refetch: vi.fn() }),
  useProjectMembers: () => ({ data: members, isLoading: false, isError: false }),
  useUpdateProjectLocation: () => ({ mutate: vi.fn(), isPending: false, isError: false, isSuccess: false }),
  useAddProjectMember: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
  useRemoveProjectMember: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
}))
vi.mock('../features/users/api', () => ({
  useUsers: () => ({
    data: [
      { id: 'u1', username: 'lead1', roles: ['lead_estimator'] },
      { id: 'u2', username: 'est1', roles: ['estimator'] },
    ],
  }),
}))
vi.mock('../features/ai/api', () => ({ useSetProjectAiOverride: () => ({ mutate: vi.fn(), isPending: false, isError: false }) }))
vi.mock('../features/tenderIntake/ProjectDocuments', () => ({
  ProjectDocuments: ({ projectId }: { projectId: string }) => <p data-testid="documents">documents of {projectId}</p>,
}))

vi.mock('../features/agent/AgentTab', () => ({
  AgentTab: ({ projectId }: { projectId: string }) => <p data-testid="agent">agent of {projectId}</p>,
}))

import { ProjectDetailPage } from './ProjectDetailPage'

function Where() {
  const loc = useLocation()
  return <p data-testid="where">{loc.pathname + loc.search}</p>
}

const renderAt = (url: string) =>
  render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route
          path="/projects/:projectId"
          element={
            <>
              <ProjectDetailPage />
              <Where />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  )

describe('ProjectDetailPage', () => {
  beforeEach(() => {
    roles = ['lead_estimator']
    projectState = { data: project, isLoading: false, isError: false }
  })

  it('shows a compact header (code, name, client, tender ref, location, members) above the documents', () => {
    renderAt('/projects/p1')
    expect(screen.getByRole('heading', { name: /AL-REEM-3 -- Al Reem Package 3/ })).toBeInTheDocument()
    expect(screen.getByText('Reem Developments')).toBeInTheDocument()
    expect(screen.getByText('T-2026-014')).toBeInTheDocument()
    expect(screen.getByText('Abu Dhabi · Al Reem Island')).toBeInTheDocument()
    expect(screen.getByText('lead1, est1')).toBeInTheDocument()
    expect(screen.getByTestId('documents')).toHaveTextContent('documents of p1')
    // The old Overview / Tender documents split is gone; the page has Documents and Agent tabs.
    expect(screen.getByRole('tab', { name: 'Documents' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.queryByTestId('agent')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Overview' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Tender documents' })).not.toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('switches to the Agent tab and back, mounting only the visible one', () => {
    renderAt('/projects/p1')
    fireEvent.click(screen.getByRole('tab', { name: 'Agent' }))
    expect(screen.getByTestId('agent')).toHaveTextContent('agent of p1')
    expect(screen.queryByTestId('documents')).not.toBeInTheDocument()
    expect(screen.getByRole('tabpanel')).toHaveAttribute('aria-labelledby', 'project-tab-agent')
    fireEvent.click(screen.getByRole('tab', { name: 'Documents' }))
    expect(screen.getByTestId('documents')).toBeInTheDocument()
    expect(screen.queryByTestId('agent')).not.toBeInTheDocument()
  })

  it('shows the Agent tab to a plain estimator too (read-only is handled inside it)', () => {
    roles = ['estimator']
    renderAt('/projects/p1')
    expect(screen.getByRole('tab', { name: 'Agent' })).toBeInTheDocument()
  })

  it('opens "Edit project" as a drawer holding members and the old Overview fields, and closes it again', () => {
    roles = ['bd_director']
    renderAt('/projects/p1')
    fireEvent.click(screen.getByRole('button', { name: 'Edit project' }))
    expect(screen.getByRole('dialog', { name: 'Edit project' })).toBeInTheDocument()
    expect(screen.getByLabelText('Emirate')).toHaveValue('Abu Dhabi')
    expect(screen.getByRole('checkbox', { name: 'Keep this project off external AI' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove lead1' })).toBeInTheDocument()
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('lets a plain estimator see members read-only and not edit the location', () => {
    roles = ['estimator']
    renderAt('/projects/p1')
    fireEvent.click(screen.getByRole('button', { name: 'Edit project' }))
    expect(screen.queryByLabelText('Emirate')).not.toBeInTheDocument()
    expect(screen.getByText(/Only a BD director or the managing director can change it/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Remove/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add member' })).not.toBeInTheDocument()
  })

  it('redirects an old ?tab= URL to the plain project URL', async () => {
    renderAt('/projects/p1?tab=tender-documents')
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent(/^\/projects\/p1$/))
    expect(screen.getByTestId('documents')).toBeInTheDocument()
  })

  it('redirects the overview tab URL too', async () => {
    renderAt('/projects/p1?tab=overview')
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent(/^\/projects\/p1$/))
  })

  it('shows the load error with a retry', () => {
    projectState = { data: undefined, isLoading: false, isError: true }
    renderAt('/projects/p1')
    expect(screen.getByRole('alert')).toHaveTextContent('boom')
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })
})
