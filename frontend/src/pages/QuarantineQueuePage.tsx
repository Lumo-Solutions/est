import { useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { useAttachInboundEmail, useDismissInboundEmail, useInboundReviewQueue, useResolveInboundTenant } from '../features/quotations/api'
import { Role } from '../lib/roles'

function ReviewRow({ email }: { email: import('../types/api').InboundEmailOut }) {
  const { hasRole } = useAuth()
  const [tenantId, setTenantId] = useState('')
  const [rfqId, setRfqId] = useState('')
  const resolveTenant = useResolveInboundTenant()
  const dismiss = useDismissInboundEmail()
  const attach = useAttachInboundEmail()

  return (
    <tr className="border-b border-slate-100">
      <td className="py-2">{email.from_address}</td>
      <td>{email.subject ?? '--'}</td>
      <td>{email.review_reasons.join(', ')}</td>
      <td>
        {email.spf_result}/{email.dkim_result}/{email.dmarc_result}
      </td>
      <td className="space-y-1">
        {hasRole(Role.PLATFORM_ADMIN) && !email.tenant_id && (
          <div className="flex gap-1">
            <input
              placeholder="Tenant ID"
              value={tenantId}
              onChange={(e) => setTenantId(e.target.value)}
              className="w-40 rounded border border-slate-300 px-1 py-0.5 text-xs"
            />
            <button
              type="button"
              onClick={() => {
                const note = window.prompt('Note (required)')
                if (note) resolveTenant.mutate(email.id, { tenant_id: tenantId, note })
              }}
              className="text-xs text-slate-600 underline"
            >
              Resolve tenant
            </button>
          </div>
        )}
        <div className="flex gap-1">
          <input
            placeholder="RFQ ID"
            value={rfqId}
            onChange={(e) => setRfqId(e.target.value)}
            className="w-40 rounded border border-slate-300 px-1 py-0.5 text-xs"
          />
          <button
            type="button"
            onClick={() => {
              const reason = window.prompt('Reason (required)')
              if (reason) attach.mutate(email.id, { rfq_id: rfqId, reason })
            }}
            className="text-xs text-slate-600 underline"
          >
            Attach to RFQ
          </button>
        </div>
        <button
          type="button"
          onClick={() => {
            const note = window.prompt('Dismiss note (required)')
            if (note) dismiss.mutate(email.id, { note })
          }}
          className="text-xs text-red-600 underline"
        >
          Dismiss
        </button>
      </td>
    </tr>
  )
}

export function QuarantineQueuePage() {
  const { data: queue, isLoading, isError, error } = useInboundReviewQueue()

  return (
    <div className="p-6">
      <h1 className="text-xl font-semibold text-slate-800">Quarantine and review queue</h1>
      {isLoading && <p className="mt-4 text-slate-500">Loading...</p>}
      {isError && <p className="mt-4 text-red-600">{error.message}</p>}
      {queue && queue.length === 0 && <p className="mt-4 text-sm text-slate-500">Nothing needs review.</p>}
      {queue && queue.length > 0 && (
        <table className="mt-4 w-full text-left text-sm">
          <thead className="border-b border-slate-200 text-slate-500">
            <tr>
              <th>From</th>
              <th>Subject</th>
              <th>Reasons</th>
              <th>SPF/DKIM/DMARC</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {queue.map((email) => (
              <ReviewRow key={email.id} email={email} />
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
