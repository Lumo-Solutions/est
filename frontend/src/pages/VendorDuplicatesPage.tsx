import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { useResolveDuplicate, useDuplicateCandidates } from '../features/vendors/api'
import { Role } from '../lib/roles'

const WRITE_ROLES = [Role.LEAD_ESTIMATOR, Role.PROCUREMENT_HEAD, Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR]

export function VendorDuplicatesPage() {
  const { hasRole } = useAuth()
  const canWrite = hasRole(...WRITE_ROLES)
  const { data: candidates, isLoading, isError, error } = useDuplicateCandidates('open')
  const resolve = useResolveDuplicate()

  return (
    <div className="p-6">
      <Link to="/vendors" className="text-sm text-slate-500 hover:text-slate-800 hover:underline">
        ← Vendors
      </Link>
      <h1 className="mt-2 text-xl font-semibold text-slate-800">Vendor duplicate review</h1>
      {!canWrite && (
        <p className="mt-1 text-xs text-slate-500">Your role can view candidates but not resolve them.</p>
      )}
      {isLoading && <p className="mt-4 text-slate-500">Loading...</p>}
      {isError && <p className="mt-4 text-red-600">{error.message}</p>}
      {candidates && candidates.length === 0 && (
        <p className="mt-4 text-slate-500">No open duplicate candidates.</p>
      )}
      {candidates && candidates.length > 0 && (
        <ul className="mt-4 space-y-3">
          {candidates.map((c) => (
            <li key={c.id} className="rounded border border-slate-200 p-3">
              <div className="flex items-center justify-between">
                <div className="text-sm">
                  <Link to={`/vendors/${c.vendor_a_id}`} className="text-slate-800 hover:underline">
                    Vendor A
                  </Link>{' '}
                  vs{' '}
                  <Link to={`/vendors/${c.vendor_b_id}`} className="text-slate-800 hover:underline">
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
                      className="rounded border border-red-300 px-2 py-1 text-xs text-red-700 hover:bg-red-50"
                    >
                      Confirm duplicate
                    </button>
                    <button
                      type="button"
                      disabled={resolve.isPending}
                      onClick={() => resolve.mutate({ candidateId: c.id, data: { resolution: 'not_duplicate' } })}
                      className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50"
                    >
                      Not a duplicate
                    </button>
                    <button
                      type="button"
                      disabled={resolve.isPending}
                      onClick={() => resolve.mutate({ candidateId: c.id, data: { resolution: 'merged' } })}
                      className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50"
                    >
                      Merged
                    </button>
                  </div>
                )}
              </div>
              {c.signals && (
                <p className="mt-1 text-xs text-slate-500">
                  {Object.entries(c.signals)
                    .map(([k, v]) => `${k}: ${Math.round(v * 100)}%`)
                    .join(', ')}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
      {resolve.isError && <p className="mt-2 text-sm text-red-600">{resolve.error.message}</p>}
    </div>
  )
}
