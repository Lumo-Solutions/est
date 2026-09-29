import { useQuery } from '@tanstack/react-query'
import { api } from '../../lib/api'
import type { UserOut } from '../../types/api'

export function useUsers({ enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: ['users'],
    enabled,
    queryFn: ({ signal }) => api.get<UserOut[]>('/users', signal),
  })
}
