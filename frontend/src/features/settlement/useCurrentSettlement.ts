import { useSettlements } from './api'

/** The project's current (is_current=true) settlement version, if any --
 * every settlement-adjacent screen (cockpit, export, win/loss) starts
 * from this. */
export function useCurrentSettlement(projectId: string | undefined) {
  const query = useSettlements(projectId)
  const current = query.data?.find((s) => s.is_current) ?? null
  return { ...query, current }
}
