import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { useCostItem, useCostItemRateAsOf, useRecordRate } from '../features/costlib/api'
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
            className="rounded border border-slate-300 px-2 py-1 text-sm"
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
            className="rounded border border-slate-300 px-2 py-1 text-sm"
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
            className="rounded border border-slate-300 px-2 py-1 text-sm"
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
            className="w-28 rounded border border-slate-300 px-2 py-1 text-sm"
          />
        </div>
        <button
          type="submit"
          disabled={recordRate.isPending}
          className="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        >
          Save rate
        </button>
      </div>
      {recordRate.isError && <p className="mt-1 text-sm text-red-600">{recordRate.error.message}</p>}
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

  if (itemLoading) return <p className="p-6 text-slate-500">Loading...</p>
  if (itemError) {
    return (
      <div className="p-6">
        <Link to="/cost-library" className="text-sm text-slate-500 hover:text-slate-800 hover:underline">
          ← Cost library
        </Link>
        <p className="mt-4 text-red-600">{itemErr.message}</p>
      </div>
    )
  }
  if (!item) return null

  return (
    <div className="p-6">
      <Link to="/cost-library" className="text-sm text-slate-500 hover:text-slate-800 hover:underline">
        ← Cost library
      </Link>
      <h1 className="mt-2 text-xl font-semibold text-slate-800">
        {item.code} — {item.description}
      </h1>
      <p className="mt-1 text-sm text-slate-500">
        UoM: {item.uom} · {item.item_type} · {item.is_active ? 'Active' : 'Inactive'}
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
              className="rounded border border-slate-300 px-2 py-1 text-sm"
            />
          </div>
          {canWrite && (
            <button
              type="button"
              onClick={() => setShowRecordForm((v) => !v)}
              className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
            >
              {showRecordForm ? 'Cancel' : 'Record new rate'}
            </button>
          )}
        </div>
        {showRecordForm && costItemId && <RecordRateForm costItemId={costItemId} onDone={() => setShowRecordForm(false)} />}

        {rateLoading && <p className="mt-3 text-sm text-slate-500">Loading rate...</p>}
        {rateError && <p className="mt-3 text-sm text-slate-500">No rate was on file for this item on {validOn}.</p>}
        {rate && (
          <div className="mt-3 rounded border border-slate-200 p-3 text-sm">
            <p className="font-medium text-slate-800">
              {rate.currency} {rate.total_rate.toFixed(2)}
            </p>
            <p className="mt-1 text-xs text-slate-500">
              Scope: {rate.scope_key} · Source: {rate.source}
              {rate.confidence !== null && ` · Confidence: ${Math.round(rate.confidence * 100)}%`}
            </p>
            {rate.components.length > 0 && (
              <table className="mt-2 w-full text-left text-xs">
                <thead className="border-b border-slate-200 text-slate-500">
                  <tr>
                    <th className="py-1">Component</th>
                    <th>Description</th>
                    <th>Qty/UoM</th>
                    <th>Unit cost</th>
                    <th>Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {rate.components.map((c) => (
                    <tr key={c.id} className="border-b border-slate-100">
                      <td className="py-1">{c.component_type}</td>
                      <td>{c.description}</td>
                      <td>{c.quantity_per_uom}</td>
                      <td>{c.unit_cost.toFixed(2)}</td>
                      <td>{c.amount.toFixed(2)}</td>
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
