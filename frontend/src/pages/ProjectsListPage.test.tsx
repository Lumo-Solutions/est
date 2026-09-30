import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ hasRole: () => true }),
}))

const createMutate = vi.fn()
vi.mock('../features/projects/api', () => ({
  useProjectsPage: () => ({ data: { items: [], total: 0, limit: 20, offset: 0 }, isLoading: false, isError: false }),
  useCreateProject: () => ({ mutate: createMutate, isPending: false, isError: false }),
}))

import { ProjectsListPage } from './ProjectsListPage'

function Where() {
  const loc = useLocation()
  return <p data-testid="where">{loc.pathname + loc.search}</p>
}

describe('ProjectsListPage', () => {
  it('lands on the new project page (the drop zone is right there) after creating it', async () => {
    createMutate.mockImplementation((_body: unknown, opts: { onSuccess: (p: { id: string }) => void }) => opts.onSuccess({ id: 'new-1' }))
    render(
      <MemoryRouter initialEntries={['/projects']}>
        <Routes>
          <Route path="/projects" element={<ProjectsListPage />} />
          <Route path="*" element={<Where />} />
        </Routes>
      </MemoryRouter>,
    )
    fireEvent.click(screen.getAllByRole('button', { name: 'New project' })[0])
    fireEvent.change(screen.getByLabelText(/Code/), { target: { value: 'P-1' } })
    fireEvent.change(screen.getByLabelText(/Name/), { target: { value: 'Tower' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create project' }))
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/projects/new-1'))
  })
})
