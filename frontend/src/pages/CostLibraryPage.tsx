import { useId, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { Badge } from '../components/Badge'
import { SkeletonRows } from '../components/Skeleton'
import { useCostItems, useCreateCostItem } from '../features/costlib/api'
import { Role } from '../lib/roles'

// Mirrors backend/app/api/v1/routes/cost_library.py's _WRITE_ROLES exactly.
const WRITE_ROLES = [Role.LEAD_ESTIMATOR, Role.PROCUREMENT_HEAD, Role.MANAGING_DIRECTOR]
const PAGE_SIZE = 20

function NewCostItemForm({ onDone }: { onDone: () => void }) {
  const [code, setCode] = useState('')
  const [description, setDescription] = useState('')
  const [uom, setUom] = useState('')
  const createItem = useCreateCostItem()

  return (
    <form
      className="mb-6 rounded border border-slate-200 p-4"
      onSubmit={(e) => {
        e.preventDefault()
        createItem.mutate({ code, description, uom }, { onSuccess: onDone })
      }}
    >
      <div className="flex flex-wrap items-end gap-2">
        <div>
          <label className="block text-xs text-slate-500" htmlFor="cost-code">
            Code
          </label>
          <input
            id="cost-code"
            required
            value={code}
            onChange={(e) => setCode(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1.5 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
          />
        </div>
        <div>
          <label className="block text-xs text-slate-500" htmlFor="cost-description">
            Description
          </label>
          <input
            id="cost-description"
            required
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1.5 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
          />
        </div>
        <div>
          <label className="block text-xs text-slate-500" htmlFor="cost-uom">
            UoM
          </label>
          <input
            id="cost-uom"
            required
            value={uom}
            onChange={(e) => setUom(e.target.value)}
            className="w-16 rounded border border-slate-300 px-2 py-1.5 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
          />
        </div>
        <button
          type="submit"
          disabled={createItem.isPending}
          className="rounded bg-brand px-3 py-1.5 text-sm font-medium text-white transition-colors duration-150 hover:bg-brand-hover disabled:opacity-50"
        >
          Create item
        </button>
      </div>
      {createItem.isError && (
        <p role="alert" className="mt-1 text-sm text-danger">
          {createItem.error.message}
        </p>
      )}
    </form>
  )
}

export function CostLibraryPage() {
  const { hasRole } = useAuth()
  const [showForm, setShowForm] = useState(false)
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const { data, isLoading, isError, error } = useCostItems({ search: search || undefined, limit: PAGE_SIZE, offset })
  const searchId = useId()

  return (
    <div className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold text-slate-800">Cost library</h1>
        {hasRole(...WRITE_ROLES) && (
          <button
            type="button"
            onClick={() => setShowForm((v) => !v)}
            className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 transition-colors duration-150 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
          >
            {showForm ? 'Cancel' : 'New cost item'}
          </button>
        )}
      </div>
      {showForm && <NewCostItemForm onDone={() => setShowForm(false)} />}
      {/* Deliberately doesn't repeat the word "code" -- Playwright's
          getByLabel() matches by substring, and an existing e2e test
          (costlib-module-e.spec.ts) does getByLabel('Code') expecting the
          create-form's own Code field uniquely; a label here containing
          "code" made that ambiguous. */}
      <label htmlFor={searchId} className="sr-only">
        Search cost items
      </label>
      <input
        id={searchId}
        value={search}
        onChange={(e) => {
          setSearch(e.target.value)
          setOffset(0)
        }}
        placeholder="Search by code or description..."
        className="mb-3 w-72 rounded border border-slate-300 px-2 py-1.5 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
      />
      {isLoading && <SkeletonRows count={6} />}
      {isError && (
        <p role="alert" className="text-danger">
          {error.message}
        </p>
      )}
      {data && data.items.length === 0 && <p className="text-slate-500">No cost items match.</p>}
      {data && data.items.length > 0 && (
        <>
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 text-slate-500">
              <tr>
                <th className="py-2 font-medium">Code</th>
                <th className="font-medium">Description</th>
                <th className="font-medium">UoM</th>
                <th className="font-medium">Type</th>
                <th className="font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((item) => (
                <tr key={item.id} className="border-b border-slate-100 hover:bg-slate-50">
                  <td className="py-2">
                    <Link
                      to={`/cost-library/${item.id}`}
                      className="rounded text-slate-800 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
                    >
                      {item.code}
                    </Link>
                  </td>
                  <td>{item.description}</td>
                  <td>{item.uom}</td>
                  <td>{item.item_type}</td>
                  <td>
                    <Badge tone={item.is_active ? 'success' : 'neutral'}>
                      {item.is_active ? 'Active' : 'Inactive'}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-2 flex items-center justify-between text-xs text-slate-500">
            <span className="tabular-nums">
              Showing {offset + 1}-{Math.min(offset + PAGE_SIZE, data.total)} of {data.total}
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                className="rounded border border-slate-300 px-2 py-1 transition-colors duration-150 hover:bg-slate-50 disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
              >
                Previous
              </button>
              <button
                type="button"
                disabled={offset + PAGE_SIZE >= data.total}
                onClick={() => setOffset(offset + PAGE_SIZE)}
                className="rounded border border-slate-300 px-2 py-1 transition-colors duration-150 hover:bg-slate-50 disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
              >
                Next
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
