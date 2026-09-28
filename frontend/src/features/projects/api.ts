import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../lib/api'
import type { ProjectCreate, ProjectLocationUpdate, ProjectMemberAdd, ProjectMemberOut, ProjectOut } from '../../types/api'

export function useProjects() {
  return useQuery({
    queryKey: ['projects'],
    queryFn: ({ signal }) => api.get<ProjectOut[]>('/projects', signal),
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

export function useAddProjectMember(projectId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: ProjectMemberAdd) => api.post<void>(`/projects/${projectId}/members`, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['projects', projectId, 'members'] }),
  })
}
