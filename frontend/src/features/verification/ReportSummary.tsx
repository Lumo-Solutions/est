import { Card, SectionHeading } from '../../components/Card'
import { Table, TableCard, Td, Th } from '../../components/Table'
import type { VerificationClass, VerificationRunOut } from '../../types/api'
import { CLASS_HELP, CLASS_LABEL, CLASS_ORDER, fmtPct } from './labels'

const ring = 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1'

export function ReportWarnings({ warnings }: { warnings: string[] }) {
  if (warnings.length === 0) return null
  return (
    <div role="alert" className="mb-4 rounded-card bg-warning-subtle p-4 text-sm text-amber-800">
      <p className="font-semibold">Read before relying on this report</p>
      <ul className="mt-1 list-disc pl-5">
        {warnings.map((w) => (
          <li key={w}>{w}</li>
        ))}
      </ul>
    </div>
  )
}

export function SummaryCards({
  run,
  active,
  onToggle,
}: {
  run: VerificationRunOut
  active: VerificationClass[]
  onToggle: (c: VerificationClass) => void
}) {
  const total = CLASS_ORDER.reduce((n, c) => n + (run.counts[c] ?? 0), 0)
  return (
    <>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        {CLASS_ORDER.map((c) => {
          const on = active.length === 1 && active[0] === c
          return (
            <button
              key={c}
              type="button"
              aria-pressed={on}
              onClick={() => onToggle(c)}
              className={`rounded-card p-4 text-left ${ring} ${on ? 'bg-brand-subtle ring-2 ring-brand' : 'bg-white hover:bg-canvas'}`}
            >
              <span className="block text-sm text-muted">{CLASS_LABEL[c]}</span>
              <span className="block text-2xl font-semibold tabular-nums text-ink-title">{run.counts[c] ?? 0}</span>
              <span className="block text-xs text-muted">{CLASS_HELP[c]}</span>
            </button>
          )
        })}
      </div>
      <p className="mt-2 text-sm text-ink-2">
        {run.summary.verifiable} of {total} lines verifiable
      </p>
    </>
  )
}

export function TradeTable({ run }: { run: VerificationRunOut }) {
  const rows = run.summary.by_trade
  if (rows.length === 0) return null
  return (
    <Card className="mt-4">
      <SectionHeading>Variance by trade</SectionHeading>
      <TableCard className="p-0">
        <Table aria-label="Variance by trade">
          <thead>
            <tr>
              <Th>Trade</Th>
              <Th numeric>Lines</Th>
              <Th numeric>Match</Th>
              <Th numeric>Variance</Th>
              <Th numeric>Missing in drawings</Th>
              <Th numeric>Not verifiable</Th>
              <Th numeric>Total abs. variance %</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t) => (
              <tr key={t.trade}>
                <Td>{t.trade}</Td>
                <Td numeric>{t.lines}</Td>
                <Td numeric>{t.match}</Td>
                <Td numeric>{t.variance}</Td>
                <Td numeric>{t.missing_in_drawings}</Td>
                <Td numeric>{t.not_verifiable}</Td>
                <Td numeric>{fmtPct(t.abs_variance_pct_sum)}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </TableCard>
    </Card>
  )
}

export function TopRisks({
  run,
  describe,
  onOpen,
}: {
  run: VerificationRunOut
  describe: (lineId: string) => string
  onOpen: (lineId: string) => void
}) {
  const risks = run.summary.top_risks
  if (risks.length === 0) return null
  return (
    <Card className="mt-4">
      <SectionHeading>Top risks</SectionHeading>
      <ul className="divide-y divide-row-rule">
        {risks.map((r) => (
          <li key={r.line_id} className="py-2 text-sm">
            <button
              type="button"
              onClick={() => onOpen(r.line_id)}
              className={`rounded text-left text-brand hover:underline ${ring}`}
            >
              {describe(r.line_id)}
            </button>
            <span className="ml-2 text-muted">
              {CLASS_LABEL[r.class]}
              {r.delta_pct != null ? `, ${fmtPct(r.delta_pct)}` : ''}
            </span>
            {r.note && <span className="block text-xs text-ink-2">{r.note}</span>}
          </li>
        ))}
      </ul>
    </Card>
  )
}
