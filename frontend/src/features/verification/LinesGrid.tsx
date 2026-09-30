import { Badge } from '../../components/Badge'
import { controlClasses } from '../../components/Field'
import { Pagination } from '../../components/Pagination'
import { Table, TableCard, Td, Th } from '../../components/Table'
import type { VerificationClass, VerificationLineOut } from '../../types/api'
import { PAGE_SIZE, type LineFilters } from './api'
import { CLASS_LABEL, CLASS_ORDER, lineDomId, CLASS_TONE, MAPPED_BY_LABEL, METHOD_LABEL, fmtPct, fmtQty } from './labels'

const ring = 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1'

export function LinesFilters({
  filters,
  trades,
  onChange,
}: {
  filters: LineFilters
  trades: string[]
  onChange: (next: LineFilters) => void
}) {
  const toggle = (c: VerificationClass) => {
    const has = filters.vclass.includes(c)
    onChange({ ...filters, offset: 0, vclass: has ? filters.vclass.filter((x) => x !== c) : [...filters.vclass, c] })
  }
  return (
    <div className="mb-3 flex flex-wrap items-end gap-4">
      <fieldset>
        <legend className="mb-1 text-xs text-muted">Class</legend>
        <div className="flex flex-wrap gap-3">
          {CLASS_ORDER.map((c) => (
            <label key={c} className="flex items-center gap-1 text-sm text-ink">
              <input
                type="checkbox"
                checked={filters.vclass.includes(c)}
                onChange={() => toggle(c)}
                className={`h-4 w-4 rounded border-slate-300 text-brand ${ring}`}
              />
              {CLASS_LABEL[c]}
            </label>
          ))}
        </div>
      </fieldset>
      <div>
        <label htmlFor="ver-trade" className="mb-1 block text-xs text-muted">
          Trade
        </label>
        <select
          id="ver-trade"
          value={filters.trade}
          onChange={(e) => onChange({ ...filters, offset: 0, trade: e.target.value })}
          className={`${controlClasses} py-1.5 text-sm`}
        >
          <option value="">All trades</option>
          {trades.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label htmlFor="ver-band" className="mb-1 block text-xs text-muted">
          Confidence
        </label>
        <select
          id="ver-band"
          value={filters.band}
          onChange={(e) => onChange({ ...filters, offset: 0, band: e.target.value as LineFilters['band'] })}
          className={`${controlClasses} py-1.5 text-sm`}
        >
          <option value="">Any confidence</option>
          <option value="low">Low (under 50%)</option>
          <option value="medium">Medium (50% to 80%)</option>
          <option value="high">High (80% and over)</option>
        </select>
      </div>
      <div>
        <label htmlFor="ver-q" className="mb-1 block text-xs text-muted">
          Search
        </label>
        <input
          id="ver-q"
          type="search"
          value={filters.q}
          onChange={(e) => onChange({ ...filters, offset: 0, q: e.target.value })}
          placeholder="Item no or description"
          className={`${controlClasses} py-1.5 text-sm`}
        />
      </div>
    </div>
  )
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  const color = value < 0.5 ? 'bg-danger' : value >= 0.8 ? 'bg-success' : 'bg-warning'
  return (
    <span className="inline-flex items-center gap-2">
      <span aria-hidden="true" className="h-1.5 w-12 rounded bg-slate-100">
        <span className={`block h-1.5 rounded ${color}`} style={{ width: `${pct}%` }} />
      </span>
      <span className="tabular-nums">{pct}%</span>
    </span>
  )
}

export function LinesGrid({
  lines,
  total,
  offset,
  selectedId,
  onSelect,
  onPage,
}: {
  lines: VerificationLineOut[]
  total: number
  offset: number
  selectedId: string | null
  onSelect: (line: VerificationLineOut) => void
  onPage: (offset: number) => void
}) {
  return (
    <>
      <TableCard>
        <Table aria-label="Verification lines">
          <thead>
            <tr>
              <Th>Item</Th>
              <Th>Description</Th>
              <Th>Class</Th>
              <Th>Unit</Th>
              <Th numeric>BOQ qty</Th>
              <Th numeric>Drawing qty</Th>
              <Th numeric>Delta %</Th>
              <Th>Confidence</Th>
              <Th>Method</Th>
            </tr>
          </thead>
          <tbody>
            {lines.map((l) => {
              const method = METHOD_LABEL[l.method]
              const mapped = MAPPED_BY_LABEL[l.mapped_by]
              return (
                <tr
                  key={l.id}
                  id={lineDomId(l.id)}
                  aria-selected={l.id === selectedId}
                  className={l.id === selectedId ? 'bg-brand-subtle' : 'hover:bg-canvas'}
                >
                  <Td>
                    <button
                      type="button"
                      onClick={() => onSelect(l)}
                      aria-label={`Open line ${l.item_no ?? l.description}`}
                      className={`rounded text-brand hover:underline ${ring}`}
                    >
                      {l.item_no ?? '--'}
                    </button>
                  </Td>
                  <Td className="max-w-xs truncate" title={l.description}>
                    {l.description}
                  </Td>
                  <Td>
                    <Badge tone={CLASS_TONE[l.vclass]}>{CLASS_LABEL[l.vclass]}</Badge>
                  </Td>
                  <Td>{l.boq_uom ?? '--'}</Td>
                  <Td numeric>{fmtQty(l.boq_quantity)}</Td>
                  <Td numeric>{fmtQty(l.drawing_quantity)}</Td>
                  <Td numeric>{fmtPct(l.delta_pct)}</Td>
                  <Td>
                    <ConfidenceBar value={l.confidence} />
                  </Td>
                  <Td>
                    <span className="flex flex-wrap gap-1">
                      {method && <Badge tone="neutral">{method}</Badge>}
                      {mapped && <Badge tone={l.mapped_by === 'user' ? 'success' : 'info'}>{mapped}</Badge>}
                    </span>
                  </Td>
                </tr>
              )
            })}
          </tbody>
        </Table>
        {lines.length === 0 && <p className="p-4 text-sm text-muted">No lines match these filters.</p>}
      </TableCard>
      <div className="mt-3 flex items-center justify-between text-sm text-muted">
        <span>
          {total === 0 ? 0 : offset + 1}-{Math.min(offset + PAGE_SIZE, total)} of {total} lines
        </span>
        <Pagination
          page={Math.floor(offset / PAGE_SIZE) + 1}
          pageCount={Math.max(1, Math.ceil(total / PAGE_SIZE))}
          onPageChange={(p) => onPage((p - 1) * PAGE_SIZE)}
        />
      </div>
    </>
  )
}
