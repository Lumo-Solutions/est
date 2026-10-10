import { ConfidenceChip, FlagChips } from './AgentBadges'
import type { AgentProposal } from './types'

/** The confidence chip and flag chips of an agent line's proposal. */
export function AgentConfidenceAndFlags({ proposal }: { proposal: AgentProposal | null }) {
  if (!proposal) return null
  return (
    <>
      <ConfidenceChip confidence={proposal.confidence} />
      <FlagChips flags={proposal.flags} />
    </>
  )
}
