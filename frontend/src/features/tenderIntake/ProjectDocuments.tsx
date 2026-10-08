import { useState } from 'react'
import { useAuth } from '../../auth/AuthContext'
import { Card } from '../../components/Card'
import { SkeletonRows } from '../../components/Skeleton'
import { MeasureAll } from '../drawings/MeasureAll'
import { AddendaRegister } from './AddendaRegister'
import { AiStatusNotice } from './AiStatusNotice'
import { Disclosure } from './Disclosure'
import { DocumentRegister } from './DocumentRegister'
import { DocumentTree } from './DocumentTree'
import { IntakeProgress } from './IntakeProgress'
import { NeedsCheckList } from './NeedsCheckList'
import { NextSteps } from './NextSteps'
import { PackControls } from './PackControls'
import { UploadPanel } from './UploadPanel'
import { useTenderTree } from './api'
import { CONFIRM_ROLES, UPLOAD_ROLES } from './lib'

const noop = () => {}

// The project page's documents panel: upload, live progress, pack controls, the files that need a check, next steps
// and the organised document tree. It runs on counts (the tree query) and pages the files it shows; the tree query
// refreshes after every mutation and polls its small summary while anything is uploading or being read.
export function ProjectDocuments({ projectId }: { projectId: string }) {
  const { hasRole } = useAuth()
  const canUpload = hasRole(...UPLOAD_ROLES)
  const canConfirm = hasRole(...CONFIRM_ROLES)
  const tree = useTenderTree(projectId)
  // The drop zone of an empty project stays up until its upload has finished: the first batch creates the package
  // (so the project stops being "empty"), but the remaining batches and the upload status live in the zone.
  const [uploadOpen, setUploadOpen] = useState(false)
  // "Add more files" opens by itself when the page is opened with an unfinished upload, so resuming is one click away.
  // Decided once, on first load: a later flip would remount the upload panel in the middle of an upload.
  const [openAddMore, setOpenAddMore] = useState<boolean | null>(null)

  if (tree.isLoading) {
    return (
      <Card className="mt-6">
        <SkeletonRows count={6} />
      </Card>
    )
  }
  if (tree.isError || !tree.data) {
    return (
      <p role="alert" className="mt-6 text-sm text-danger">
        {tree.error?.message ?? 'Could not load the project documents.'}
      </p>
    )
  }

  const { summary, groups, folders, packages } = tree.data
  if (openAddMore === null) setOpenAddMore(packages.some((p) => p.status === 'uploading'))
  const empty = summary.total === 0 && summary.pending_upload === 0 && summary.packages_processing === 0

  return (
    <div>
      <AiStatusNotice summary={summary} />
      {(empty || uploadOpen) &&
        (canUpload ? (
          <UploadPanel projectId={projectId} onUploaded={() => setUploadOpen(false)} onUploadStart={() => setUploadOpen(true)} variant="hero" />
        ) : (
          <Card className="mt-6">
            <p className="text-base text-ink-2">No tender documents have been uploaded yet. An estimator or above can upload them.</p>
          </Card>
        ))}
      <IntakeProgress summary={summary} packages={packages} />
      <PackControls projectId={projectId} packages={packages} canConfirm={canConfirm} />
      {!empty && (
        <>
          <NeedsCheckList projectId={projectId} summary={summary} canConfirm={canConfirm} />
          <NextSteps projectId={projectId} summary={summary} />
          <MeasureAll projectId={projectId} />
          {canUpload && (
            <Disclosure title="Add more files" hint="Drop another folder, files or a zip." defaultOpen={openAddMore ?? false}>
              <UploadPanel projectId={projectId} onUploaded={noop} />
            </Disclosure>
          )}
          <DocumentTree projectId={projectId} summary={summary} groups={groups} folders={folders} canConfirm={canConfirm} />
          <Disclosure title="Registers" hint="Addenda and the project document register." lazy>
            <AddendaRegister projectId={projectId} />
            <DocumentRegister projectId={projectId} />
          </Disclosure>
        </>
      )}
    </div>
  )
}
