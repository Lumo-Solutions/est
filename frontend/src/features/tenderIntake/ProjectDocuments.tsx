import { useAuth } from '../../auth/AuthContext'
import { Card } from '../../components/Card'
import { SkeletonRows } from '../../components/Skeleton'
import { AddendaRegister } from './AddendaRegister'
import { AiStatusNotice } from './AiStatusNotice'
import { Disclosure } from './Disclosure'
import { DocumentRegister } from './DocumentRegister'
import { DocumentTree } from './DocumentTree'
import { IntakeProgress } from './IntakeProgress'
import { NeedsCheckList } from './NeedsCheckList'
import { NextSteps } from './NextSteps'
import { UploadPanel } from './UploadPanel'
import { useTenderTree } from './api'
import { CONFIRM_ROLES, UPLOAD_ROLES } from './lib'

const noop = () => {}

// The project page's documents panel: upload, live reading progress, the files that need a check,
// next steps and the organised document tree. The tree query refreshes after every mutation and
// polls while anything is being read.
export function ProjectDocuments({ projectId }: { projectId: string }) {
  const { hasRole } = useAuth()
  const canUpload = hasRole(...UPLOAD_ROLES)
  const canConfirm = hasRole(...CONFIRM_ROLES)
  const tree = useTenderTree(projectId)

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

  const { items, summary } = tree.data
  const empty = items.length === 0 && summary.packages_processing === 0

  return (
    <div>
      <AiStatusNotice summary={summary} />
      {empty &&
        (canUpload ? (
          <UploadPanel projectId={projectId} onUploaded={noop} variant="hero" />
        ) : (
          <Card className="mt-6">
            <p className="text-base text-ink-2">No tender documents have been uploaded yet. An estimator or above can upload them.</p>
          </Card>
        ))}
      <IntakeProgress summary={summary} />
      {items.length > 0 && (
        <>
          <NeedsCheckList projectId={projectId} items={items} canConfirm={canConfirm} />
          <NextSteps projectId={projectId} items={items} summary={summary} />
          {canUpload && (
            <Disclosure title="Add more files" hint="Drop another folder, files or a zip.">
              <UploadPanel projectId={projectId} onUploaded={noop} />
            </Disclosure>
          )}
          <DocumentTree projectId={projectId} items={items} canConfirm={canConfirm} />
          <Disclosure title="Registers" hint="Addenda and the project document register." lazy>
            <AddendaRegister projectId={projectId} />
            <DocumentRegister projectId={projectId} />
          </Disclosure>
        </>
      )}
    </div>
  )
}
