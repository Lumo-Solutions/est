import { useId, useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { Badge, type BadgeTone } from '../components/Badge'
import { SkeletonRows } from '../components/Skeleton'
import { TextPromptModal } from '../components/TextPromptModal'
import { useAttachInboundEmail, useDismissInboundEmail, useInboundReviewQueue, useResolveInboundTenant } from '../features/quotations/api'
import { Role } from '../lib/roles'
import type { InboundEmailOut } from '../types/api'

type OpenPrompt = { kind: 'resolve-tenant' | 'attach' | 'dismiss'; email: InboundEmailOut; extra: string } | null

// docs/ui-design-system.md section 4.8. backend/app/core/enums.py's
// AuthCheckResult (pass/fail/none/unknown) -- used for the SPF/DKIM/DMARC
// verdicts shown per inbound email.
const AUTH_RESULT_TONE: Record<string, BadgeTone> = {
  pass: 'success',
  fail: 'danger',
  none: 'neutral',
  unknown: 'warning',
}

function AuthResultBadge({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span className="text-xs text-slate-600">{label}</span>
      <Badge tone={AUTH_RESULT_TONE[value] ?? 'neutral'}>{value}</Badge>
    </span>
  )
}

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
  const tenantIdInputId = useId()
  const rfqIdInputId = useId()

  return (
    <tr className="border-b border-slate-100 hover:bg-slate-50">
      <td className="py-2">{email.from_address}</td>
      <td>{email.subject ?? '--'}</td>
      <td>{email.review_reasons.join(', ')}</td>
      <td>
        <span className="flex flex-wrap items-center gap-2">
          <AuthResultBadge label="SPF" value={email.spf_result} />
          <AuthResultBadge label="DKIM" value={email.dkim_result} />
          <AuthResultBadge label="DMARC" value={email.dmarc_result} />
        </span>
      </td>
      <td className="space-y-1 py-2">
        {hasRole(Role.PLATFORM_ADMIN) && !email.tenant_id && (
          <div className="flex gap-1">
            <label htmlFor={tenantIdInputId} className="sr-only">
              Tenant ID
            </label>
            <input
              id={tenantIdInputId}
              placeholder="Tenant ID"
              value={tenantId}
              onChange={(e) => setTenantId(e.target.value)}
              className="w-40 rounded border border-slate-300 px-1 py-0.5 text-xs focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
            />
            <button
              type="button"
              onClick={() => onOpenPrompt('resolve-tenant', email, tenantId)}
              className="rounded text-xs text-slate-500 underline hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
            >
              Resolve tenant
            </button>
          </div>
        )}
        <div className="flex gap-1">
          <label htmlFor={rfqIdInputId} className="sr-only">
            RFQ ID
          </label>
          <input
            id={rfqIdInputId}
            placeholder="RFQ ID"
            value={rfqId}
            onChange={(e) => setRfqId(e.target.value)}
            className="w-40 rounded border border-slate-300 px-1 py-0.5 text-xs focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
          />
          <button
            type="button"
            onClick={() => onOpenPrompt('attach', email, rfqId)}
            className="rounded text-xs text-slate-500 underline hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
          >
            Attach to RFQ
          </button>
        </div>
        <button
          type="button"
          onClick={() => onOpenPrompt('dismiss', email, '')}
          className="rounded text-xs text-danger underline hover:text-red-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
        >
          Dismiss
        </button>
      </td>
    </tr>
  )
}

// Mirrors the nav gate on AppShell's Inbox item (see the comment there for
// why platform_admin is included). UX nicety only -- the server remains the
// only real enforcement (_REVIEW_ROLES / require_roles(Role.PLATFORM_ADMIN)
// in backend/app/api/v1/routes/quotation_ingestion.py).
const PAGE_ROLES = [Role.PROCUREMENT_HEAD, Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR, Role.PLATFORM_ADMIN]

export function QuarantineQueuePage() {
  const { hasRole } = useAuth()
  const { data: queue, isLoading, isError, error } = useInboundReviewQueue()
  const [openPrompt, setOpenPrompt] = useState<OpenPrompt>(null)
  const resolveTenant = useResolveInboundTenant()
  const dismiss = useDismissInboundEmail()
  const attach = useAttachInboundEmail()

  if (!hasRole(...PAGE_ROLES)) {
    return (
      <div className="p-6">
        <h1 className="text-xl font-semibold text-slate-800">Quarantine and review queue</h1>
        <p className="mt-2 text-sm text-slate-500">You don't have access to this page.</p>
      </div>
    )
  }

  return (
    <div className="p-6">
      <h1 className="text-xl font-semibold text-slate-800">Quarantine and review queue</h1>
      {isLoading && (
        <div className="mt-4">
          <SkeletonRows count={5} />
        </div>
      )}
      {isError && (
        <p role="alert" className="mt-4 text-danger">
          {error.message}
        </p>
      )}
      {queue && queue.length === 0 && <p className="mt-4 text-sm text-slate-500">Nothing needs review.</p>}
      {queue && queue.length > 0 && (
        <table className="mt-4 w-full text-left text-sm">
          <thead className="border-b border-slate-200 text-slate-500">
            <tr>
              <th className="py-2 font-medium">From</th>
              <th className="font-medium">Subject</th>
              <th className="font-medium">Reasons</th>
              <th className="font-medium">SPF/DKIM/DMARC</th>
              <th className="font-medium">Actions</th>
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
      {/* These three mutations previously had no isError display at all --
          the same gap already fixed on every other mutation in Phases 2-3
          (e.g. BoqReconciliationPage's Reconcile button). The modal closes
          immediately on submit (matching every other TextPromptModal call
          site in this app), so a failure surfaces here at the page level,
          not inside the now-closed dialog. */}
      {resolveTenant.isError && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {resolveTenant.error.message}
        </p>
      )}
      {attach.isError && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {attach.error.message}
        </p>
      )}
      {dismiss.isError && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {dismiss.error.message}
        </p>
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
