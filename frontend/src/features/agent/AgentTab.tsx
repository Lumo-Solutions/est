import { useState } from 'react'
import { Bot } from 'lucide-react'
import { useAuth } from '../../auth/AuthContext'
import { Button } from '../../components/Button'
import { SkeletonRows } from '../../components/Skeleton'
import { useAgentRun, useAgentRuns, useAgentSteps, useRunAction, useStartRun } from './api'
import { ChatPanel } from './ChatPanel'
import { Coverage } from './Coverage'
import { EstimateModal } from './EstimateModal'
import { AGENT_ROLES, READ_ONLY_REASON } from './labels'
import { RunProgress } from './RunProgress'
import { RunSummary } from './RunSummary'
import { Trace } from './Trace'
import type { AgentEstimate, RunAction } from './types'

interface ModalState {
  runId: string
  estimate: AgentEstimate | null
}

// The Agent tab of the project page: start a run, watch it, read what it did, and talk to it.
export function AgentTab({ projectId }: { projectId: string }) {
  const { hasRole } = useAuth()
  const canAct = hasRole(...AGENT_ROLES)
  const [selectedId, setSelectedId] = useState<string | undefined>()
  const [modal, setModal] = useState<ModalState | null>(null)
  const [modalError, setModalError] = useState<string | null>(null)
  const [startError, setStartError] = useState<string | null>(null)
  const [offerDraft, setOfferDraft] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  const runs = useAgentRuns(projectId)
  const runId = selectedId ?? runs.data?.[0]?.id
  const run = useAgentRun(runId)
  const steps = useAgentSteps(runId, run.data?.status)
  const start = useStartRun(projectId)
  const act = useRunAction(projectId)

  const startRun = (createDraft: boolean) => {
    setStartError(null)
    setOfferDraft(false)
    start.mutate(createDraft ? { create_draft: true } : {}, {
      onSuccess: (r) => {
        setSelectedId(r.id)
        if (r.status === 'awaiting_confirm') {
          setModalError(null)
          setModal({ runId: r.id, estimate: r.estimate })
        }
      },
      onError: (e) => {
        setStartError(e.message)
        // A 409 about the settlement not being a draft can be resolved by starting a new draft version.
        setOfferDraft(/draft/i.test(e.message) && 'status' in e && (e as { status?: number }).status === 409)
      },
    })
  }

  const onConfirm = () => {
    if (!modal) return
    setModalError(null)
    act.mutate(
      { runId: modal.runId, action: 'confirm' },
      { onSuccess: () => setModal(null), onError: (e) => setModalError(e.message) },
    )
  }
  // Declining the estimate cancels the waiting run so it does not block the next one.
  const onDecline = () => {
    if (!modal) return
    act.mutate({ runId: modal.runId, action: 'cancel' })
    setModal(null)
  }
  const onAction = (action: RunAction) => {
    if (!runId) return
    setActionError(null)
    act.mutate({ runId, action }, { onError: (e) => setActionError(e.message) })
  }

  const detail = run.data
  return (
    <div className="mt-4 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-card bg-white p-5">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-section font-semibold text-ink-title">
            <Bot className="h-5 w-5" aria-hidden="true" />
            Estimation agent
          </h2>
          <p className="text-sm text-muted">
            Reads the tender files it needs and proposes costs into a draft settlement. A person confirms every line
            before submit.
          </p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <Button
            onClick={() => startRun(false)}
            loading={start.isPending}
            disabled={!canAct}
            aria-describedby={canAct ? undefined : 'agent-run-reason'}
          >
            Run estimation agent
          </Button>
          {!canAct && (
            <p id="agent-run-reason" className="max-w-xs text-right text-xs text-muted">
              {READ_ONLY_REASON}
            </p>
          )}
        </div>
      </div>

      {startError && (
        <div role="alert" className="flex flex-wrap items-center gap-3 rounded-card bg-danger-subtle p-4 text-sm text-red-700">
          <span>{startError}</span>
          {offerDraft && canAct && (
            <Button size="sm" variant="secondary" onClick={() => startRun(true)} loading={start.isPending}>
              Start a new draft version
            </Button>
          )}
        </div>
      )}

      {runs.isLoading || (runId && run.isLoading) ? (
        <SkeletonRows count={4} />
      ) : runs.isError ? (
        <div role="alert" className="text-sm text-danger">
          {runs.error.message}{' '}
          <Button size="sm" variant="secondary" onClick={() => runs.refetch()}>
            Retry
          </Button>
        </div>
      ) : !runId ? (
        <p className="rounded-card bg-white p-5 text-sm text-muted">
          No agent run yet for this project.{canAct ? ' Use "Run estimation agent" to start one.' : ''}
        </p>
      ) : run.isError ? (
        <div role="alert" className="text-sm text-danger">
          {run.error.message}{' '}
          <Button size="sm" variant="secondary" onClick={() => run.refetch()}>
            Retry
          </Button>
        </div>
      ) : detail ? (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
          <div className="min-w-0 space-y-4">
            <RunProgress
              run={detail}
              canAct={canAct}
              busy={act.isPending}
              error={actionError}
              onAction={onAction}
              onReview={() => {
                setModalError(null)
                setModal({ runId: detail.id, estimate: detail.estimate })
              }}
            />
            <RunSummary run={detail} />
            <Trace
              plan={detail.plan}
              sections={detail.sections}
              steps={steps.data}
              loading={steps.isLoading}
              error={steps.isError ? steps.error.message : null}
            />
            <Coverage sections={detail.sections} />
          </div>
          <div className="min-w-0">
            <ChatPanel projectId={projectId} canChat={canAct} />
          </div>
        </div>
      ) : null}

      {!runId && !runs.isLoading && !runs.isError && (
        <div className="min-w-0 xl:max-w-sm">
          <ChatPanel projectId={projectId} canChat={canAct} />
        </div>
      )}

      {modal && (
        <EstimateModal
          estimate={modal.estimate}
          busy={act.isPending}
          error={modalError}
          onConfirm={onConfirm}
          onCancel={onDecline}
        />
      )}
    </div>
  )
}
