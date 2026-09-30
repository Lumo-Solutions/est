import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../lib/api'
import type { AiSettingsOut, AiStatusOut, AiUsageOut, ProjectAiOverrideOut } from '../../types/api'

export function useAiStatus() {
  return useQuery({
    queryKey: ['ai', 'status'],
    queryFn: ({ signal }) => api.get<AiStatusOut>('/ai/status', signal),
  })
}

// Only enable for bd_director / managing_director; the endpoint 403s for
// every other role.
export function useAiUsage(days = 30, enabled = true) {
  return useQuery({
    queryKey: ['ai', 'usage', { days }],
    queryFn: ({ signal }) => api.get<AiUsageOut>(`/admin/ai-usage?days=${days}`, signal),
    enabled,
  })
}

export function useSetExternalAi() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (externalAiAllowed: boolean) =>
      api.put<AiSettingsOut>('/admin/ai-settings', { external_ai_allowed: externalAiAllowed }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['ai'] }),
  })
}

export function useSetProjectAiOverride(projectId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (externalAiOverride: boolean | null) =>
      api.put<ProjectAiOverrideOut>(`/projects/${projectId}/ai-override`, {
        external_ai_override: externalAiOverride,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['ai'] }),
  })
}
