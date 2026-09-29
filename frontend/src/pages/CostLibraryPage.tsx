import { useId, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { Badge } from '../components/Badge'
import { SkeletonRows } from '../components/Skeleton'
import { useCostItems, useCreateCostItem } from '../features/costlib/api'
import { Role } from '../lib/roles'
import { PageTitle } from '../components/PageTitle'
import { Table, TableCard, Td, Th } from '../components/Table'

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
      className="mb-6 rounded-card p-5 bg-white"
      onSubmit={(e) => {
        e.preventDefault()
        createItem.mutate({ code, description, uom }, { onSuccess: onDone })
      }}
    >
      <div className="flex flex-wrap items-end gap-2">
        <div>
          <label className="mb-1 block text-sm text-ink" htmlFor="cost-code">
            Code
          </label>
          <input
            id="cost-code"
            required
            value={code}
            onChange={(e) => setCode(e.target.value)}
            className="rounded-control border border-outline px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand text-ink"
          />
        </div>
        <div>
          <label className="mb-1 block text-sm text-ink" htmlFor="cost-description">
            Description
          </label>
          <input
            id="cost-description"
            required
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="rounded-control border border-outline px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand text-ink"
          />
        </div>
        <div>
          <label className="mb-1 block text-sm text-ink" htmlFor="cost-uom">
            UoM
          </label>
          <input
            id="cost-uom"
            required
            value={uom}
            onChange={(e) => setUom(e.target.value)}
            className="w-16 rounded-control border border-outline px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand text-ink"
          />
        </div>
        <button
          type="submit"
          disabled={createItem.isPending}
          className="rounded-control bg-brand px-4 py-1.5 text-sm font-medium text-white transition-colors duration-150 hover:bg-brand-hover disabled:opacity-50"
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
    <div className="px-6 py-6 xl:px-10">
      <div className="mb-4 flex items-center justify-between">
        <PageTitle>Cost library</PageTitle>
        {hasRole(...WRITE_ROLES) && (
          <button
            type="button"
            onClick={() => setShowForm((v) => !v)}
            className="rounded-pill border border-brand px-4 py-1.5 text-sm text-brand transition-colors duration-150 hover:bg-brand-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
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
        className="mb-3 w-72 rounded-control border border-outline px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand text-ink"
      />
      {isLoading && <SkeletonRows count={6} />}
      {isError && (
        <p role="alert" className="text-danger">
          {error.message}
        </p>
      )}
      {data && data.items.length === 0 && <p className="text-muted">No cost items match.</p>}
      {data && data.items.length > 0 && (
        <>
          <TableCard>
            <Table density="comfortable">
              <thead className="border-b border-hairline text-muted">
                <tr>
                  <Th>Code</Th>
                  <Th>Description</Th>
                  <Th>UoM</Th>
                  <Th>Type</Th>
                  <Th>Status</Th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr key={item.id} className="border-b border-row-rule hover:bg-canvas">
                    <Td>
                      <Link
                        to={`/cost-library/${item.id}`}
                        className="rounded text-ink hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
                      >
                        {item.code}
                      </Link>
                    </Td>
                    <Td>{item.description}</Td>
                    <Td>{item.uom}</Td>
                    <Td>{item.item_type}</Td>
                    <Td>
                      <Badge tone={item.is_active ? 'success' : 'neutral'}>
                        {item.is_active ? 'Active' : 'Inactive'}
                      </Badge>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </TableCard>
          <div className="mt-2 flex items-center justify-between text-xs text-muted">
            <span className="tabular-nums">
              Showing {offset + 1}-{Math.min(offset + PAGE_SIZE, data.total)} of {data.total}
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                className="rounded-pill border border-brand px-2 py-1 transition-colors duration-150 hover:bg-brand-subtle disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
              >
                Previous
              </button>
              <button
                type="button"
                disabled={offset + PAGE_SIZE >= data.total}
                onClick={() => setOffset(offset + PAGE_SIZE)}
                className="rounded-pill border border-brand px-2 py-1 transition-colors duration-150 hover:bg-brand-subtle disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
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
