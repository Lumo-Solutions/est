import { useId, useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { Badge, type BadgeTone } from '../components/Badge'
import { SkeletonRows } from '../components/Skeleton'
import { TextPromptModal } from '../components/TextPromptModal'
import { useAttachInboundEmail, useDismissInboundEmail, useInboundReviewQueue, useResolveInboundTenant } from '../features/quotations/api'
import { Role } from '../lib/roles'
import type { InboundEmailOut } from '../types/api'
import { PageTitle } from '../components/PageTitle'
import { Table, TableCard, Td, Th } from '../components/Table'

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
      <span className="text-xs text-ink-2">{label}</span>
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
    <tr className="border-b border-row-rule hover:bg-canvas">
      <Td>{email.from_address}</Td>
      <Td>{email.subject ?? '--'}</Td>
      <Td>{email.review_reasons.join(', ')}</Td>
      <Td>
        <span className="flex flex-wrap items-center gap-2">
          <AuthResultBadge label="SPF" value={email.spf_result} />
          <AuthResultBadge label="DKIM" value={email.dkim_result} />
          <AuthResultBadge label="DMARC" value={email.dmarc_result} />
        </span>
      </Td>
      <Td className="space-y-1">
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
              className="w-40 rounded-lg border border-outline px-1 py-0.5 text-xs focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand text-ink"
            />
            <button
              type="button"
              onClick={() => onOpenPrompt('resolve-tenant', email, tenantId)}
              className="rounded text-xs text-muted underline hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
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
            className="w-40 rounded-lg border border-outline px-1 py-0.5 text-xs focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand text-ink"
          />
          <button
            type="button"
            onClick={() => onOpenPrompt('attach', email, rfqId)}
            className="rounded text-xs text-muted underline hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
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
      </Td>
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
      <div className="px-6 py-6 xl:px-10">
        <PageTitle>Quarantine and review queue</PageTitle>
        <p className="mt-2 text-sm text-muted">You don't have access to this page.</p>
      </div>
    )
  }

  return (
    <div className="mx-6 my-6 rounded-card bg-white p-6 xl:mx-10">
      <PageTitle>Quarantine and review queue</PageTitle>
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
      {queue && queue.length === 0 && <p className="mt-4 text-sm text-muted">Nothing needs review.</p>}
      {queue && queue.length > 0 && (
        <TableCard>
          <Table density="comfortable" className="mt-4">
            <thead className="border-b border-hairline text-muted">
              <tr>
                <Th>From</Th>
                <Th>Subject</Th>
                <Th>Reasons</Th>
                <Th>SPF/DKIM/DMARC</Th>
                <Th>Actions</Th>
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
          </Table>
        </TableCard>
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
