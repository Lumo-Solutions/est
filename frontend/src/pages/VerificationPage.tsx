import { useEffect, useId, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { Button } from '../components/Button'
import { Card, SectionHeading } from '../components/Card'
import { PageTitle } from '../components/PageTitle'
import { SkeletonRows } from '../components/Skeleton'
import { AiStatusNotice } from '../features/ai/AiStatusNotice'
import {
  EMPTY_FILTERS,
  PAGE_SIZE,
  isActive,
  useAnnotationSummary,
  useReadAnnotations,
  useRetryVerification,
  useStartVerification,
  useVerificationExport,
  useVerificationLines,
  useVerificationRun,
  useVerificationRuns,
  type LineFilters,
} from '../features/verification/api'
import { LineDetailPanel } from '../features/verification/LineDetailPanel'
import { LinesFilters, LinesGrid } from '../features/verification/LinesGrid'
import { PHASE_LABEL, lineDomId } from '../features/verification/labels'
import { ReportWarnings, SummaryCards, TopRisks, TradeTable } from '../features/verification/ReportSummary'
import { Role } from '../lib/roles'
import type { VerificationClass, VerificationRunOut } from '../types/api'

// Mirrors the backend: POST /projects/{pid}/verification-runs and
// drawing-annotations:read are lead_estimator and above; estimators are 403.
const RUN_ROLES = [Role.LEAD_ESTIMATOR, Role.PROCUREMENT_HEAD, Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR]

function AnnotationsPanel({ projectId, canRead }: { projectId: string; canRead: boolean }) {
  const { data: s } = useAnnotationSummary(projectId)
  const read = useReadAnnotations(projectId)
  return (
    <Card className="mt-4">
      <SectionHeading
        action={
          canRead ? (
            <Button variant="secondary" size="sm" loading={read.isPending} onClick={() => read.mutate()}>
              Read annotations with AI
            </Button>
          ) : undefined
        }
      >
        Drawing annotations
      </SectionHeading>
      {s ? (
        <p className="text-sm text-ink">
          {s.sheets} sheets: {s.done} read, {s.queued} queued, {s.unread} unread, {s.unavailable} unavailable,{' '}
          {s.failed} failed, {s.skipped} skipped. {s.annotations} annotations found.
        </p>
      ) : (
        <p className="text-sm text-muted">Annotation summary not loaded.</p>
      )}
      <p className="mt-1 text-xs text-muted">
        Annotated quantities are read from the sheets as written; they are never estimated.
      </p>
      {read.isSuccess && (
        <p role="status" className="mt-1 text-xs text-ink-2">
          {read.data.queued_sheets} sheets queued for reading.
        </p>
      )}
      {read.isError && (
        <p role="alert" className="mt-1 text-sm text-danger">
          {read.error.message}
        </p>
      )}
    </Card>
  )
}

function RunProgress({ run }: { run: VerificationRunOut }) {
  const pct = run.progress_total > 0 ? Math.round((run.progress_done / run.progress_total) * 100) : 0
  return (
    <Card className="mt-4" role="status" aria-live="polite">
      <p className="text-base font-medium text-ink-title">
        {run.status === 'queued' ? 'Queued' : (run.phase && PHASE_LABEL[run.phase]) || 'Running'}
      </p>
      <progress
        className="mt-2 h-2 w-full"
        max={Math.max(run.progress_total, 1)}
        value={run.progress_done}
        aria-label="Verification progress"
      />
      <p className="mt-1 text-xs text-muted">
        {run.progress_done} of {run.progress_total} ({pct}%)
      </p>
    </Card>
  )
}

function ReportSection({ projectId, run }: { projectId: string; run: VerificationRunOut }) {
  const runId = run.id
  const [filters, setFilters] = useState<LineFilters>(EMPTY_FILTERS)
  const [selectedLineId, setSelectedLineId] = useState<string | null>(null)
  const [pendingLineId, setPendingLineId] = useState<string | null>(null)

  const lines = useVerificationLines(runId, filters)
  const items = useMemo(() => {
    const all = lines.data?.items ?? []
    // The API filters a single class; several selected classes are applied here.
    return filters.vclass.length > 1 ? all.filter((l) => filters.vclass.includes(l.vclass)) : all
  }, [lines.data, filters.vclass])
  const selectedLine = items.find((l) => l.id === selectedLineId) ?? null

  // A top-risk click may target a line on another page: walk pages until found
  // (state adjusted during render, React's documented derived-state pattern).
  if (pendingLineId && lines.data && !lines.isPlaceholderData) {
    if (lines.data.items.some((l) => l.id === pendingLineId)) {
      setSelectedLineId(pendingLineId)
      setPendingLineId(null)
    } else if (filters.offset + PAGE_SIZE < lines.data.total) {
      setFilters({ ...filters, offset: filters.offset + PAGE_SIZE })
    } else {
      setPendingLineId(null)
    }
  }

  useEffect(() => {
    if (selectedLineId) document.getElementById(lineDomId(selectedLineId))?.scrollIntoView?.({ block: 'center' })
  }, [selectedLineId])

  const toggleClass = (c: VerificationClass) =>
    setFilters((f) => ({ ...f, offset: 0, vclass: f.vclass.length === 1 && f.vclass[0] === c ? [] : [c] }))

  const openRisk = (lineId: string) => {
    setFilters(EMPTY_FILTERS)
    setPendingLineId(lineId)
  }

  const describeLine = (lineId: string) => {
    const l = lines.data?.items.find((x) => x.id === lineId)
    return l ? `${l.item_no ? `${l.item_no} -- ` : ''}${l.description}` : `Line ${lineId.slice(0, 8)}`
  }

  return (
    <div className="mt-4">
      <ReportWarnings warnings={run.warnings} />
      <SummaryCards run={run} active={filters.vclass} onToggle={toggleClass} />
      <p className="mt-1 text-xs text-muted">
        {run.ai_calls} AI calls, ${run.ai_cost_usd.toFixed(2)}
      </p>
      <TradeTable run={run} />
      <TopRisks run={run} describe={describeLine} onOpen={openRisk} />

      <Card className="mt-4">
        <SectionHeading>Lines</SectionHeading>
        <LinesFilters filters={filters} trades={run.summary.by_trade.map((t) => t.trade)} onChange={setFilters} />
        {lines.isError && (
          <p role="alert" className="mb-2 text-danger">
            {lines.error.message}
          </p>
        )}
        {lines.isLoading ? (
          <SkeletonRows count={6} />
        ) : (
          <div className="flex gap-4">
            <div className="min-w-0 flex-1">
              <LinesGrid
                lines={items}
                total={lines.data?.total ?? 0}
                offset={filters.offset}
                selectedId={selectedLineId}
                onSelect={(l) => setSelectedLineId(l.id)}
                onPage={(offset) => setFilters((f) => ({ ...f, offset }))}
              />
            </div>
            {selectedLine && runId && (
              <LineDetailPanel
                key={selectedLine.id}
                projectId={projectId}
                runId={runId}
                line={selectedLine}
                onClose={() => setSelectedLineId(null)}
              />
            )}
          </div>
        )}
      </Card>
    </div>
  )
}

export function VerificationPage() {
  const { projectId } = useParams()
  const { hasRole } = useAuth()
  const canRun = hasRole(...RUN_ROLES)
  const aiCheckboxId = useId()
  const [useAi, setUseAi] = useState(true)
  const [chosenRunId, setChosenRunId] = useState<string | null>(null)

  const runs = useVerificationRuns(projectId)
  const runId = chosenRunId ?? runs.data?.[0]?.id
  const runQuery = useVerificationRun(runId)
  const run = runQuery.data ?? runs.data?.find((r) => r.id === runId)
  const start = useStartVerification(projectId)
  const retry = useRetryVerification(projectId)
  const exportRun = useVerificationExport(runId)

  const ready = run?.status === 'ready'

  const startError = start.error ?? retry.error

  return (
    <div className="px-6 py-6 xl:px-10">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
        <PageTitle>Drawing vs BOQ verification</PageTitle>
        {canRun && (
          <div className="flex flex-col items-end gap-2">
            <Button
              loading={start.isPending}
              disabled={isActive(run)}
              onClick={() => start.mutate(useAi, { onSuccess: (r) => setChosenRunId(r.id) })}
            >
              Start verification
            </Button>
            <label htmlFor={aiCheckboxId} className="flex items-center gap-2 text-sm text-ink">
              <input
                id={aiCheckboxId}
                type="checkbox"
                checked={useAi}
                onChange={(e) => setUseAi(e.target.checked)}
                className="h-4 w-4 rounded border-slate-300 text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
              />
              Use AI to map BOQ lines to drawing evidence
            </label>
            <AiStatusNotice />
          </div>
        )}
      </div>
      {startError && (
        <p role="alert" className="mb-2 text-danger">
          {startError.message}
        </p>
      )}

      {projectId && <AnnotationsPanel projectId={projectId} canRead={canRun} />}

      {runs.isLoading && (
        <div className="mt-4">
          <SkeletonRows count={4} />
        </div>
      )}
      {runs.isError && (
        <p role="alert" className="mt-4 text-danger">
          {runs.error.message}
        </p>
      )}
      {runs.data && runs.data.length === 0 && (
        <p className="mt-4 text-base text-muted">
          No verification has been run for this project yet.
          {canRun ? ' Start one to compare the BOQ with the drawings.' : ''}
        </p>
      )}

      {runs.data && runs.data.length > 0 && (
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <label htmlFor="ver-run" className="text-sm text-muted">
            Run
          </label>
          <select
            id="ver-run"
            value={runId ?? ''}
            onChange={(e) => setChosenRunId(e.target.value)}
            className="rounded-control border border-outline bg-white px-3 py-1.5 text-sm text-ink focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand"
          >
            {runs.data.map((r) => (
              <option key={r.id} value={r.id}>
                {new Date(r.created_at).toLocaleString()} - {r.status}
                {r.use_ai ? ' - AI' : ''}
              </option>
            ))}
          </select>
          {ready && runId && (
            <span className="ml-auto flex gap-2">
              <Button variant="secondary" size="sm" loading={exportRun.isPending} onClick={() => exportRun.mutate('xlsx')}>
                Export Excel
              </Button>
              <Button variant="secondary" size="sm" loading={exportRun.isPending} onClick={() => exportRun.mutate('pdf')}>
                Export PDF
              </Button>
            </span>
          )}
        </div>
      )}
      {exportRun.isError && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {exportRun.error.message}
        </p>
      )}

      {run && isActive(run) && <RunProgress run={run} />}

      {run?.status === 'failed' && (
        <Card className="mt-4">
          <p role="alert" className="text-base text-danger">
            Verification failed{run.error ? `: ${run.error}` : '.'}
          </p>
          {canRun && (
            <Button
              className="mt-2"
              variant="secondary"
              size="sm"
              loading={retry.isPending}
              onClick={() => retry.mutate(run.id, { onSuccess: (r) => setChosenRunId(r.id) })}
            >
              Retry
            </Button>
          )}
        </Card>
      )}

      {run && ready && projectId && <ReportSection key={run.id} projectId={projectId} run={run} />}
    </div>
  )
}
