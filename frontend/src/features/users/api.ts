import { useQuery } from '@tanstack/react-query'
import { api } from '../../lib/api'
import type { UserOut } from '../../types/api'

export function useUsers() {
  return useQuery({
    queryKey: ['users'],
    queryFn: ({ signal }) => api.get<UserOut[]>('/users', signal),
  })
}
