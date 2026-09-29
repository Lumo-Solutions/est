import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { SkeletonRows } from '../components/Skeleton'
import { useResolveDuplicate, useDuplicateCandidates } from '../features/vendors/api'
import { Role } from '../lib/roles'
import { PageTitle } from '../components/PageTitle'

const WRITE_ROLES = [Role.LEAD_ESTIMATOR, Role.PROCUREMENT_HEAD, Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR]

export function VendorDuplicatesPage() {
  const { hasRole } = useAuth()
  const canWrite = hasRole(...WRITE_ROLES)
  const { data: candidates, isLoading, isError, error } = useDuplicateCandidates('open')
  const resolve = useResolveDuplicate()

  return (
    <div className="mx-6 my-6 rounded-card bg-white p-6 xl:mx-10">
      <Link
        to="/vendors"
        className="rounded text-sm text-muted hover:text-ink hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
      >
        ← Vendors
      </Link>
      <PageTitle>Vendor duplicate review</PageTitle>
      {!canWrite && (
        <p className="mt-1 text-xs text-muted">Your role can view candidates but not resolve them.</p>
      )}
      {isLoading && (
        <div className="mt-4">
          <SkeletonRows count={3} />
        </div>
      )}
      {isError && (
        <p role="alert" className="mt-4 text-danger">
          {error.message}
        </p>
      )}
      {candidates && candidates.length === 0 && (
        <p className="mt-4 text-muted">No open duplicate candidates.</p>
      )}
      {candidates && candidates.length > 0 && (
        <ul className="mt-4 space-y-3">
          {candidates.map((c) => (
            <li key={c.id} className="rounded-card p-5 bg-white">
              <div className="flex items-center justify-between">
                <div className="text-sm">
                  <Link
                    to={`/vendors/${c.vendor_a_id}`}
                    className="rounded text-ink hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
                  >
                    Vendor A
                  </Link>{' '}
                  vs{' '}
                  <Link
                    to={`/vendors/${c.vendor_b_id}`}
                    className="rounded text-ink hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
                  >
                    Vendor B
                  </Link>{' '}
                  — {Math.round(c.score * 100)}% match
                </div>
                {canWrite && (
                  <div className="flex gap-2">
                    <button
                      type="button"
                      disabled={resolve.isPending}
                      onClick={() =>
                        resolve.mutate({ candidateId: c.id, data: { resolution: 'confirmed_duplicate' } })
                      }
                      className="rounded-pill border border-red-700 px-2 py-1 text-xs text-danger transition-colors duration-150 hover:bg-danger-subtle disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
                    >
                      Confirm duplicate
                    </button>
                    <button
                      type="button"
                      disabled={resolve.isPending}
                      onClick={() => resolve.mutate({ candidateId: c.id, data: { resolution: 'not_duplicate' } })}
                      className="rounded-pill border border-brand px-2 py-1 text-xs text-brand transition-colors duration-150 hover:bg-brand-subtle disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
                    >
                      Not a duplicate
                    </button>
                    <button
                      type="button"
                      disabled={resolve.isPending}
                      onClick={() => resolve.mutate({ candidateId: c.id, data: { resolution: 'merged' } })}
                      className="rounded-pill border border-brand px-2 py-1 text-xs text-brand transition-colors duration-150 hover:bg-brand-subtle disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
                    >
                      Merged
                    </button>
                  </div>
                )}
              </div>
              {c.signals && (
                <p className="mt-1 text-xs text-muted">
                  {Object.entries(c.signals)
                    .map(([k, v]) => `${k}: ${Math.round(v * 100)}%`)
                    .join(', ')}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
      {resolve.isError && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {resolve.error.message}
        </p>
      )}
    </div>
  )
}
