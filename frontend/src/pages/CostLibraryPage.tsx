import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
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
            className="rounded border border-slate-300 px-2 py-1 text-sm"
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
            className="rounded border border-slate-300 px-2 py-1 text-sm"
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
            className="w-16 rounded border border-slate-300 px-2 py-1 text-sm"
          />
        </div>
        <button
          type="submit"
          disabled={createItem.isPending}
          className="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        >
          Create item
        </button>
      </div>
      {createItem.isError && <p className="mt-1 text-sm text-red-600">{createItem.error.message}</p>}
    </form>
  )
}

export function CostLibraryPage() {
  const { hasRole } = useAuth()
  const [showForm, setShowForm] = useState(false)
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const { data, isLoading, isError, error } = useCostItems({ search: search || undefined, limit: PAGE_SIZE, offset })

  return (
    <div className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold text-slate-800">Cost library</h1>
        {hasRole(...WRITE_ROLES) && (
          <button
            type="button"
            onClick={() => setShowForm((v) => !v)}
            className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
          >
            {showForm ? 'Cancel' : 'New cost item'}
          </button>
        )}
      </div>
      {showForm && <NewCostItemForm onDone={() => setShowForm(false)} />}
      <input
        value={search}
        onChange={(e) => {
          setSearch(e.target.value)
          setOffset(0)
        }}
        placeholder="Search by code or description..."
        className="mb-3 w-72 rounded border border-slate-300 px-2 py-1 text-sm"
      />
      {isLoading && <p className="text-slate-500">Loading...</p>}
      {isError && <p className="text-red-600">{error.message}</p>}
      {data && data.items.length === 0 && <p className="text-slate-500">No cost items match.</p>}
      {data && data.items.length > 0 && (
        <>
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 text-slate-500">
              <tr>
                <th className="py-2">Code</th>
                <th>Description</th>
                <th>UoM</th>
                <th>Type</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((item) => (
                <tr key={item.id} className="border-b border-slate-100 hover:bg-slate-50">
                  <td className="py-2">
                    <Link to={`/cost-library/${item.id}`} className="text-slate-800 hover:underline">
                      {item.code}
                    </Link>
                  </td>
                  <td>{item.description}</td>
                  <td>{item.uom}</td>
                  <td>{item.item_type}</td>
                  <td>{item.is_active ? 'Active' : 'Inactive'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-2 flex items-center justify-between text-xs text-slate-500">
            <span>
              Showing {offset + 1}-{Math.min(offset + PAGE_SIZE, data.total)} of {data.total}
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                className="rounded border border-slate-300 px-2 py-1 disabled:opacity-40"
              >
                Previous
              </button>
              <button
                type="button"
                disabled={offset + PAGE_SIZE >= data.total}
                onClick={() => setOffset(offset + PAGE_SIZE)}
                className="rounded border border-slate-300 px-2 py-1 disabled:opacity-40"
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
