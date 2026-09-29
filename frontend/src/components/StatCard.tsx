import type { LucideIcon } from 'lucide-react'

// Figma Accounts/Loans/Investments stat cards: round pastel icon tile +
// muted label + 20/600 value. The tile colour is decorative (aria-hidden
// icon beside a text label), so it carries no contrast requirement.
export type StatTone = 'amber' | 'blue' | 'pink' | 'teal'

const TILE: Record<StatTone, string> = {
  amber: 'bg-tile-amber text-amber-700',
  blue: 'bg-tile-blue text-brand',
  pink: 'bg-tile-pink text-red-700',
  teal: 'bg-tile-teal text-teal-700',
}

export function StatCard({
  icon: Icon,
  tone = 'blue',
  label,
  value,
}: {
  icon: LucideIcon
  tone?: StatTone
  label: string
  value: React.ReactNode
}) {
  return (
    <div className="flex items-center gap-4 rounded-card bg-white p-5">
      <span className={`flex h-14 w-14 shrink-0 items-center justify-center rounded-full ${TILE[tone]}`}>
        <Icon aria-hidden="true" className="h-6 w-6" />
      </span>
      <div className="min-w-0">
        <p className="text-base text-muted">{label}</p>
        <p className="text-kpi font-semibold tabular-nums text-ink">{value}</p>
      </div>
    </div>
  )
}
