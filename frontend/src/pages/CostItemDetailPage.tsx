import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { Badge } from '../components/Badge'
import { SkeletonRows } from '../components/Skeleton'
import { useCostItem, useCostItemRateAsOf, useRecordRate } from '../features/costlib/api'
import { formatMoney } from '../lib/format'
import { Role } from '../lib/roles'
import type { CostRateComponentIn } from '../types/api'

const WRITE_ROLES = [Role.LEAD_ESTIMATOR, Role.PROCUREMENT_HEAD, Role.MANAGING_DIRECTOR]

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

function RecordRateForm({ costItemId, onDone }: { costItemId: string; onDone: () => void }) {
  const [validFrom, setValidFrom] = useState(today())
  const [componentType, setComponentType] = useState('material')
  const [componentDescription, setComponentDescription] = useState('')
  const [unitCost, setUnitCost] = useState('')
  const recordRate = useRecordRate(costItemId)

  return (
    <form
      className="mt-3 rounded border border-slate-200 p-4"
      onSubmit={(e) => {
        e.preventDefault()
        const component: CostRateComponentIn = {
          component_type: componentType,
          description: componentDescription,
          unit_cost: Number(unitCost),
        }
        recordRate.mutate({ valid_from: validFrom, components: [component] }, { onSuccess: onDone })
      }}
    >
      <h3 className="text-sm font-semibold text-slate-800">Record a new rate</h3>
      <p className="mt-1 text-xs text-slate-500">
        A single labeled component is enough to get started -- add more via the API for a fuller breakdown.
      </p>
      <div className="mt-2 flex flex-wrap items-end gap-2">
        <div>
          <label className="block text-xs text-slate-500" htmlFor="rate-valid-from">
            Valid from
          </label>
          <input
            id="rate-valid-from"
            type="date"
            required
            value={validFrom}
            onChange={(e) => setValidFrom(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1.5 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
          />
        </div>
        <div>
          <label className="block text-xs text-slate-500" htmlFor="component-type">
            Component type
          </label>
          <input
            id="component-type"
            required
            value={componentType}
            onChange={(e) => setComponentType(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1.5 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
          />
        </div>
        <div>
          <label className="block text-xs text-slate-500" htmlFor="component-description">
            Description
          </label>
          <input
            id="component-description"
            required
            value={componentDescription}
            onChange={(e) => setComponentDescription(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1.5 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
          />
        </div>
        <div>
          <label className="block text-xs text-slate-500" htmlFor="unit-cost">
            Unit cost
          </label>
          <input
            id="unit-cost"
            type="number"
            step="0.01"
            required
            value={unitCost}
            onChange={(e) => setUnitCost(e.target.value)}
            className="w-28 rounded border border-slate-300 px-2 py-1.5 text-sm tabular-nums focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
          />
        </div>
        <button
          type="submit"
          disabled={recordRate.isPending}
          className="rounded bg-brand px-3 py-1.5 text-sm font-medium text-white transition-colors duration-150 hover:bg-brand-hover disabled:opacity-50"
        >
          Save rate
        </button>
      </div>
      {recordRate.isError && (
        <p role="alert" className="mt-1 text-sm text-danger">
          {recordRate.error.message}
        </p>
      )}
    </form>
  )
}

export function CostItemDetailPage() {
  const { hasRole } = useAuth()
  const { costItemId } = useParams()
  const [validOn, setValidOn] = useState(today())
  const [showRecordForm, setShowRecordForm] = useState(false)
  const { data: item, isLoading: itemLoading, isError: itemError, error: itemErr } = useCostItem(costItemId)
  const { data: rate, isLoading: rateLoading, isError: rateError } = useCostItemRateAsOf(costItemId, validOn)
  const canWrite = hasRole(...WRITE_ROLES)

  const backLink = (
    <Link
      to="/cost-library"
      className="rounded text-sm text-slate-500 hover:text-slate-800 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
    >
      ← Cost library
    </Link>
  )

  if (itemLoading) {
    return (
      <div className="p-6">
        {backLink}
        <div className="mt-4">
          <SkeletonRows count={4} />
        </div>
      </div>
    )
  }
  if (itemError) {
    return (
      <div className="p-6">
        {backLink}
        <p role="alert" className="mt-4 text-danger">
          {itemErr.message}
        </p>
      </div>
    )
  }
  if (!item) return null

  return (
    <div className="p-6">
      {backLink}
      <h1 className="mt-2 text-xl font-semibold text-slate-800">
        {item.code} — {item.description}
      </h1>
      <p className="mt-1 flex items-center gap-2 text-sm text-slate-500">
        UoM: {item.uom} · {item.item_type} · <Badge tone={item.is_active ? 'success' : 'neutral'}>{item.is_active ? 'Active' : 'Inactive'}</Badge>
      </p>

      <div className="mt-6">
        <h2 className="text-sm font-semibold text-slate-800">Rate</h2>
        <div className="mt-2 flex items-end gap-2">
          <div>
            <label className="block text-xs text-slate-500" htmlFor="rate-as-of">
              As of date
            </label>
            <input
              id="rate-as-of"
              type="date"
              value={validOn}
              onChange={(e) => setValidOn(e.target.value)}
              className="rounded border border-slate-300 px-2 py-1.5 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
            />
          </div>
          {canWrite && (
            <button
              type="button"
              onClick={() => setShowRecordForm((v) => !v)}
              className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 transition-colors duration-150 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
            >
              {showRecordForm ? 'Cancel' : 'Record new rate'}
            </button>
          )}
        </div>
        {showRecordForm && costItemId && <RecordRateForm costItemId={costItemId} onDone={() => setShowRecordForm(false)} />}

        {rateLoading && (
          <div className="mt-3">
            <SkeletonRows count={2} />
          </div>
        )}
        {rateError && <p className="mt-3 text-sm text-slate-500">No rate was on file for this item on {validOn}.</p>}
        {rate && (
          <div className="mt-3 rounded border border-slate-200 p-3 text-sm">
            <p className="font-medium tabular-nums text-slate-800">{formatMoney(rate.total_rate, rate.currency)}</p>
            <p className="mt-1 text-xs text-slate-500">
              Scope: {rate.scope_key} · Source: {rate.source}
              {rate.confidence !== null && ` · Confidence: ${Math.round(rate.confidence * 100)}%`}
            </p>
            {rate.components.length > 0 && (
              <table className="mt-2 w-full text-left text-xs">
                <thead className="border-b border-slate-200 text-slate-500">
                  <tr>
                    <th className="py-1 font-medium">Component</th>
                    <th className="font-medium">Description</th>
                    <th className="font-medium">Qty/UoM</th>
                    <th className="font-medium">Unit cost</th>
                    <th className="font-medium">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {rate.components.map((c) => (
                    <tr key={c.id} className="border-b border-slate-100">
                      <td className="py-1">{c.component_type}</td>
                      <td>{c.description}</td>
                      <td className="tabular-nums">{c.quantity_per_uom}</td>
                      <td className="tabular-nums">{formatMoney(c.unit_cost, rate.currency)}</td>
                      <td className="tabular-nums">{formatMoney(c.amount, rate.currency)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
