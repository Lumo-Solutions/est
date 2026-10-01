import { useState } from 'react'
import { Button } from '../../components/Button'
import { Card } from '../../components/Card'
import { ConfirmModal } from '../../components/ConfirmModal'
import { useCancelTenderPackage, usePauseTenderPackage, useResumeTenderPackage } from './api'
import type { PackageProgress } from './types'

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

// Pause, Resume and Cancel for the packs that are still uploading, being read, or paused. Lead estimators and above
// only: everyone else sees nothing here.
export function PackControls({ projectId, packages, canConfirm }: { projectId: string; packages: PackageProgress[]; canConfirm: boolean }) {
  const pause = usePauseTenderPackage(projectId)
  const resume = useResumeTenderPackage(projectId)
  const cancel = useCancelTenderPackage(projectId)
  const [cancelling, setCancelling] = useState<PackageProgress | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

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
                <Button size="sm" loading={busyId === p.id && resume.isPending} onClick={() => run(resume, p, 'resume')} aria-label={`Resume ${packName(p)}`}>
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
