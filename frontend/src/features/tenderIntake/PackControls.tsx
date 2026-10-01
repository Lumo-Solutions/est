import { useEffect, useRef, useState } from 'react'
import { Button } from '../../components/Button'
import { Card } from '../../components/Card'
import { ConfirmModal } from '../../components/ConfirmModal'
import { useCancelTenderPackage, useCostEstimate, usePauseTenderPackage, useResumeTenderPackage } from './api'
import { CostEstimateModal } from './CostEstimateModal'
import { CostConfirmationRequiredError, type CostEstimate, type PackageProgress } from './types'

const CONTROLLABLE = ['uploading', 'processing', 'paused']

const PACK_STATUS_LABEL: Record<string, string> = {
  uploading: 'Uploading',
  processing: 'Processing',
  paused: 'Paused',
  cancelled: 'Cancelled',
  ready: 'Ready',
  failed: 'Failed',
}

const packStatusLabel = (status: string) => PACK_STATUS_LABEL[status] ?? status

function packName(p: PackageProgress): string {
  return p.label || `upload of ${p.created_at.slice(0, 10)}`
}

const msg = (e: unknown) => (e instanceof Error ? e.message : 'Request failed')

// Loads the estimate for a pack about to be resumed and reports it once (mounted only while that check runs).
function EstimateLoader({ packageId, onLoaded, onFailed }: { packageId: string; onLoaded: (e: CostEstimate) => void; onFailed: (e: Error) => void }) {
  const { data, error } = useCostEstimate(packageId)
  const reported = useRef(false)
  useEffect(() => {
    if (reported.current) return
    if (data) {
      reported.current = true
      onLoaded(data)
    } else if (error) {
      reported.current = true
      onFailed(error)
    }
  }, [data, error, onLoaded, onFailed])
  return null
}

// Pause, Resume and Cancel for the packs that are still uploading, being read, or paused. Lead estimators and above
// only: everyone else sees nothing here.
export function PackControls({ projectId, packages, canConfirm }: { projectId: string; packages: PackageProgress[]; canConfirm: boolean }) {
  const pause = usePauseTenderPackage(projectId)
  const resume = useResumeTenderPackage(projectId)
  const cancel = useCancelTenderPackage(projectId)
  const [cancelling, setCancelling] = useState<PackageProgress | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [checking, setChecking] = useState<PackageProgress | null>(null)
  const [review, setReview] = useState<{ pack: PackageProgress; estimate: CostEstimate } | null>(null)

  const active = packages.filter((p) => CONTROLLABLE.includes(p.status))
  if (!canConfirm || active.length === 0) return null

  const run = (m: typeof pause, p: PackageProgress, verb: string) => {
    setError(null)
    setBusyId(p.id)
    m.mutate(p.id, {
      onError: (e) => setError(`Could not ${verb} ${packName(p)}: ${msg(e)}`),
      onSettled: () => setBusyId(null),
    })
  }

  const doResume = (p: PackageProgress) => {
    setError(null)
    setBusyId(p.id)
    resume.mutate(p.id, {
      onError: (e) => {
        if (e instanceof CostConfirmationRequiredError && e.estimate) setReview({ pack: p, estimate: e.estimate })
        else setError(`Could not resume ${packName(p)}: ${msg(e)}`)
      },
      onSettled: () => setBusyId(null),
    })
  }

  // Resume looks at the estimated AI cost first; only a pack that needs confirmation opens the modal.
  const startResume = (p: PackageProgress) => {
    setError(null)
    setBusyId(p.id)
    setChecking(p)
  }

  return (
    <Card className="mt-6" aria-label="Pack controls">
      <ul className="divide-y divide-row-rule">
        {active.map((p) => (
          <li key={p.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 py-2">
            <p className="min-w-0 text-sm text-ink">
              <span className="font-medium">{p.label || 'Upload'}</span>
              <span className="ml-2 text-ink-2">
                {packStatusLabel(p.status)}, {p.uploaded} of {p.expected_count} files uploaded
              </span>
            </p>
            <div className="flex items-center gap-2">
              {p.status === 'paused' ? (
                <Button size="sm" loading={busyId === p.id && (resume.isPending || checking?.id === p.id)} onClick={() => startResume(p)} aria-label={`Resume ${packName(p)}`}>
                  Resume
                </Button>
              ) : (
                <Button size="sm" variant="secondary" loading={busyId === p.id && pause.isPending} onClick={() => run(pause, p, 'pause')} aria-label={`Pause ${packName(p)}`}>
                  Pause
                </Button>
              )}
              <Button size="sm" variant="secondary" disabled={busyId === p.id} onClick={() => setCancelling(p)} aria-label={`Cancel ${packName(p)}`}>
                Cancel
              </Button>
            </div>
          </li>
        ))}
      </ul>
      {error && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {error}
        </p>
      )}
      {checking && (
        <EstimateLoader
          key={checking.id}
          packageId={checking.id}
          onLoaded={(estimate) => {
            const p = checking
            setChecking(null)
            if (estimate.confirmation_required) {
              setBusyId(null)
              setReview({ pack: p, estimate })
            } else doResume(p)
          }}
          onFailed={(e) => {
            const p = checking
            setChecking(null)
            setBusyId(null)
            setError(`Could not check the AI cost of ${packName(p)}: ${msg(e)}`)
          }}
        />
      )}
      {review && (
        <CostEstimateModal
          open
          projectId={projectId}
          packageId={review.pack.id}
          estimate={review.estimate}
          onClose={() => setReview(null)}
          onConfirmed={() => doResume(review.pack)}
        />
      )}
      <ConfirmModal
        open={cancelling !== null}
        title={cancelling ? `Cancel ${packName(cancelling)}?` : 'Cancel this pack?'}
        message="Files not yet read are left out; files already sorted stay. This cannot be undone."
        confirmLabel="Cancel pack"
        onCancel={() => setCancelling(null)}
        onConfirm={() => {
          const p = cancelling
          setCancelling(null)
          if (p) run(cancel, p, 'cancel')
        }}
      />
    </Card>
  )
}
