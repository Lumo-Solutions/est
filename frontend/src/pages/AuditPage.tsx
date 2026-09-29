import { useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { SkeletonRows } from '../components/Skeleton'
import { useAuditEvents, useVerifyAuditChain } from '../features/audit/api'
import { Role } from '../lib/roles'
import { PageTitle } from '../components/PageTitle'

export function AuditPage() {
  const { hasRole } = useAuth()
  const [entityType, setEntityType] = useState('')
  const [entityId, setEntityId] = useState('')
  const { data: events, isLoading, isError, error } = useAuditEvents({ entityType: entityType || undefined, entityId: entityId || undefined })

  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const verifyChain = useVerifyAuditChain()

  return (
    <div className="px-6 py-6 xl:px-10">
      <PageTitle>Audit viewer</PageTitle>

      <div className="mt-3 flex gap-2">
        <div>
          <label htmlFor="audit-entity-type" className="sr-only">
            Filter by entity type
          </label>
          <input
            id="audit-entity-type"
            placeholder="Entity type"
            value={entityType}
            onChange={(e) => setEntityType(e.target.value)}
            className="rounded-control border border-outline px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand text-ink"
          />
        </div>
        <div>
          <label htmlFor="audit-entity-id" className="sr-only">
            Filter by entity ID
          </label>
          <input
            id="audit-entity-id"
            placeholder="Entity ID"
            value={entityId}
            onChange={(e) => setEntityId(e.target.value)}
            className="rounded-control border border-outline px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand text-ink"
          />
        </div>
      </div>

      {isLoading && (
        <div className="mt-4">
          <SkeletonRows count={6} />
        </div>
      )}
      {isError && (
        <p role="alert" className="mt-4 text-sm text-danger">
          {error.message}
        </p>
      )}
      {events && events.length === 0 && <p className="mt-4 text-sm text-muted">No audit events match this filter.</p>}
      {events && events.length > 0 && (
        <div className="overflow-x-auto rounded-card bg-white p-2">
          <table className="mt-4 w-full text-left text-sm">
            <thead className="border-b border-hairline font-medium text-muted">
              <tr>
                <th className="py-2">When</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Entity</th>
                <th>Hash</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <tr key={e.id} className="border-b border-row-rule text-xs hover:bg-canvas">
                  <td className="py-2">{new Date(e.occurred_at).toLocaleString()}</td>
                  <td>{e.actor_sub ?? 'system'} ({e.actor_roles.join(',')})</td>
                  <td>{e.action}</td>
                  <td>{e.entity_type}{e.entity_id ? `:${e.entity_id.slice(0, 8)}` : ''}</td>
                  <td className="font-mono">{e.event_hash.slice(0, 12)}...</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {hasRole(Role.MANAGING_DIRECTOR) && (
        <div className="mt-6 border-t border-hairline pt-4">
          <h2 className="text-lg font-semibold text-ink-title">Verify hash chain</h2>
          <div className="mt-2 flex items-end gap-2">
            <div>
              <label htmlFor="audit-verify-from" className="mb-1 block text-sm text-ink">
                From
              </label>
              <input
                id="audit-verify-from"
                type="date"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
                className="rounded-control border border-outline px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand text-ink"
              />
            </div>
            <div>
              <label htmlFor="audit-verify-to" className="mb-1 block text-sm text-ink">
                To
              </label>
              <input
                id="audit-verify-to"
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
                className="rounded-control border border-outline px-3 py-2 text-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand text-ink"
              />
            </div>
            <button
              type="button"
              disabled={!dateFrom || !dateTo || verifyChain.isPending}
              onClick={() => verifyChain.mutate({ dateFrom, dateTo })}
              className="rounded-control bg-brand px-4 py-1.5 text-sm font-medium text-white transition-colors duration-150 hover:bg-brand-hover disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
            >
              Verify
            </button>
          </div>
          {verifyChain.data && (
            <p
              role={verifyChain.data.ok ? 'status' : 'alert'}
              className={`mt-2 text-sm ${verifyChain.data.ok ? 'text-emerald-700' : 'text-danger'}`}
            >
              {verifyChain.data.ok ? 'Chain intact.' : `Chain broken: ${verifyChain.data.detail}`}
            </p>
          )}
          {verifyChain.isError && (
            <p role="alert" className="mt-2 text-sm text-danger">
              {verifyChain.error.message}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
