import { useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { useAuditEvents, useVerifyAuditChain } from '../features/audit/api'
import { Role } from '../lib/roles'

export function AuditPage() {
  const { hasRole } = useAuth()
  const [entityType, setEntityType] = useState('')
  const [entityId, setEntityId] = useState('')
  const { data: events, isLoading, isError, error } = useAuditEvents({ entityType: entityType || undefined, entityId: entityId || undefined })

  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const verifyChain = useVerifyAuditChain()

  return (
    <div className="p-6">
      <h1 className="text-xl font-semibold text-slate-800">Audit viewer</h1>

      <div className="mt-3 flex gap-2">
        <input placeholder="Entity type" value={entityType} onChange={(e) => setEntityType(e.target.value)} className="rounded border border-slate-300 px-2 py-1 text-sm" />
        <input placeholder="Entity ID" value={entityId} onChange={(e) => setEntityId(e.target.value)} className="rounded border border-slate-300 px-2 py-1 text-sm" />
      </div>

      {isLoading && <p className="mt-4 text-slate-500">Loading...</p>}
      {isError && <p className="mt-4 text-red-600">{error.message}</p>}
      {events && (
        <table className="mt-4 w-full text-left text-sm">
          <thead className="border-b border-slate-200 text-slate-500">
            <tr>
              <th>When</th>
              <th>Actor</th>
              <th>Action</th>
              <th>Entity</th>
              <th>Hash</th>
            </tr>
          </thead>
          <tbody>
            {events.map((e) => (
              <tr key={e.id} className="border-b border-slate-100 text-xs">
                <td>{new Date(e.occurred_at).toLocaleString()}</td>
                <td>{e.actor_sub ?? 'system'} ({e.actor_roles.join(',')})</td>
                <td>{e.action}</td>
                <td>{e.entity_type}{e.entity_id ? `:${e.entity_id.slice(0, 8)}` : ''}</td>
                <td className="font-mono">{e.event_hash.slice(0, 12)}...</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {hasRole(Role.MANAGING_DIRECTOR) && (
        <div className="mt-6 border-t border-slate-200 pt-4">
          <h2 className="text-sm font-semibold text-slate-800">Verify hash chain</h2>
          <div className="mt-2 flex items-end gap-2">
            <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className="rounded border border-slate-300 px-2 py-1 text-sm" />
            <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className="rounded border border-slate-300 px-2 py-1 text-sm" />
            <button
              type="button"
              disabled={!dateFrom || !dateTo || verifyChain.isPending}
              onClick={() => verifyChain.mutate({ dateFrom, dateTo })}
              className="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
            >
              Verify
            </button>
          </div>
          {verifyChain.data && (
            <p className={`mt-2 text-sm ${verifyChain.data.ok ? 'text-green-700' : 'text-red-600'}`}>
              {verifyChain.data.ok ? 'Chain intact.' : `Chain broken: ${verifyChain.data.detail}`}
            </p>
          )}
          {verifyChain.isError && <p className="mt-2 text-sm text-red-600">{verifyChain.error.message}</p>}
        </div>
      )}
    </div>
  )
}
