import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../lib/api'
import type { Page, ProjectCreate, ProjectLocationUpdate, ProjectMemberAdd, ProjectMemberOut, ProjectOut } from '../../types/api'

// No-args, unbounded call -- GET /projects with neither `limit` nor
// `offset` keeps returning the full, bare ProjectOut[] array it always has
// (see app/api/v1/routes/projects.py). LayerTradeMappingAdmin.tsx and
// TolerancesAdmin.tsx rely on exactly this behavior to populate a
// project-picker <select> with every project -- do not add params here;
// use useProjectsPage() below for a paginated view instead.
export function useProjects() {
  return useQuery({
    queryKey: ['projects'],
    queryFn: ({ signal }) => api.get<ProjectOut[]>('/projects', signal),
  })
}

// Paginated view for ProjectsListPage: passing `limit`/`offset` switches
// GET /projects to the `Page` envelope shape ({items, total, limit,
// offset}), the same pagination convention GET /vendors and GET
// /cost-items already use (see useVendors() in features/vendors/api.ts).
export function useProjectsPage(params: { limit?: number; offset?: number } = {}) {
  const { limit = 20, offset = 0 } = params
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  return useQuery({
    queryKey: ['projects', 'page', limit, offset],
    queryFn: ({ signal }) => api.get<Page<ProjectOut>>(`/projects?${query}`, signal),
  })
}

export function useProject(projectId: string | undefined) {
  return useQuery({
    queryKey: ['projects', projectId],
    queryFn: ({ signal }) => api.get<ProjectOut>(`/projects/${projectId}`, signal),
    enabled: Boolean(projectId),
  })
}

export function useCreateProject() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: ProjectCreate) => api.post<ProjectOut>('/projects', data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['projects'] }),
  })
}

export function useUpdateProjectLocation(projectId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: ProjectLocationUpdate) => api.patch<ProjectOut>(`/projects/${projectId}/location`, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['projects', projectId] }),
  })
}

export function useProjectMembers(projectId: string | undefined) {
  return useQuery({
    queryKey: ['projects', projectId, 'members'],
    queryFn: ({ signal }) => api.get<ProjectMemberOut[]>(`/projects/${projectId}/members`, signal),
    enabled: Boolean(projectId),
  })
}

export function useRemoveProjectMember(projectId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (userId: string) => api.delete<void>(`/projects/${projectId}/members/${userId}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['projects', projectId, 'members'] }),
  })
}

export function useAddProjectMember(projectId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: ProjectMemberAdd) => api.post<void>(`/projects/${projectId}/members`, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['projects', projectId, 'members'] }),
  })
}
