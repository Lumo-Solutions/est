import { useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { TextPromptModal } from '../components/TextPromptModal'
import { useAttachInboundEmail, useDismissInboundEmail, useInboundReviewQueue, useResolveInboundTenant } from '../features/quotations/api'
import { Role } from '../lib/roles'
import type { InboundEmailOut } from '../types/api'

type OpenPrompt = { kind: 'resolve-tenant' | 'attach' | 'dismiss'; email: InboundEmailOut; extra: string } | null

function ReviewRow({
  email,
  onOpenPrompt,
}: {
  email: InboundEmailOut
  onOpenPrompt: (kind: 'resolve-tenant' | 'attach' | 'dismiss', email: InboundEmailOut, extra: string) => void
}) {
  const { hasRole } = useAuth()
  const [tenantId, setTenantId] = useState('')
  const [rfqId, setRfqId] = useState('')

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
              onClick={() => onOpenPrompt('resolve-tenant', email, tenantId)}
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
            onClick={() => onOpenPrompt('attach', email, rfqId)}
            className="text-xs text-slate-600 underline"
          >
            Attach to RFQ
          </button>
        </div>
        <button
          type="button"
          onClick={() => onOpenPrompt('dismiss', email, '')}
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
  const [openPrompt, setOpenPrompt] = useState<OpenPrompt>(null)
  const resolveTenant = useResolveInboundTenant()
  const dismiss = useDismissInboundEmail()
  const attach = useAttachInboundEmail()

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
              <ReviewRow
                key={email.id}
                email={email}
                onOpenPrompt={(kind, email, extra) => setOpenPrompt({ kind, email, extra })}
              />
            ))}
          </tbody>
        </table>
      )}
      <TextPromptModal
        open={openPrompt?.kind === 'resolve-tenant'}
        title="Resolve tenant"
        message="Note (required)"
        onCancel={() => setOpenPrompt(null)}
        onSubmit={(note) => {
          if (openPrompt) resolveTenant.mutate(openPrompt.email.id, { tenant_id: openPrompt.extra, note })
          setOpenPrompt(null)
        }}
      />
      <TextPromptModal
        open={openPrompt?.kind === 'attach'}
        title="Attach to RFQ"
        message="Reason (required)"
        onCancel={() => setOpenPrompt(null)}
        onSubmit={(reason) => {
          if (openPrompt) attach.mutate(openPrompt.email.id, { rfq_id: openPrompt.extra, reason })
          setOpenPrompt(null)
        }}
      />
      <TextPromptModal
        open={openPrompt?.kind === 'dismiss'}
        title="Dismiss"
        message="Dismiss note (required)"
        submitLabel="Dismiss"
        onCancel={() => setOpenPrompt(null)}
        onSubmit={(note) => {
          if (openPrompt) dismiss.mutate(openPrompt.email.id, { note })
          setOpenPrompt(null)
        }}
      />
    </div>
  )
}
