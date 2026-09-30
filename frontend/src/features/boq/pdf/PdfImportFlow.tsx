import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Button } from '../../../components/Button'
import { AiStatusNotice } from '../../ai/AiStatusNotice'
import { useAiStatus } from '../../ai/api'
import {
  useBoqPdfExtraction,
  useCommitBoqPdfExtraction,
  useRetryBoqPdfExtraction,
  useSaveBoqPdfRows,
  useStartBoqPdfExtraction,
} from './api'
import { PdfExtractionProgress } from './PdfExtractionProgress'
import { PdfRowsGrid } from './PdfRowsGrid'

// The PDF branch of the BOQ import wizard: options -> extraction progress ->
// row review grid -> import. Either `file` (an upload) or `documentId` (an
// already uploaded tender document) is the source.
export function PdfImportFlow({
  projectId,
  file,
  documentId,
  sourceName,
  canImport,
}: {
  projectId: string
  file: File | null
  documentId: string | null
  sourceName: string
  canImport: boolean
}) {
  const [useAi, setUseAi] = useState(true)
  const [extractionId, setExtractionId] = useState<string | null>(null)
  const { data: aiStatus } = useAiStatus()
  const start = useStartBoqPdfExtraction(projectId)
  const query = useBoqPdfExtraction(extractionId)
  const save = useSaveBoqPdfRows(extractionId)
  const commit = useCommitBoqPdfExtraction(projectId, extractionId)
  const retry = useRetryBoqPdfExtraction(extractionId)
  const extraction = query.data
  const aiUnavailable = aiStatus != null && !aiStatus.available

  if (!canImport) {
    return (
      <p role="status" className="mt-4 text-sm text-ink-2">
        Importing a BOQ from a PDF is limited to lead estimators, procurement heads and managing directors. Ask one of
        them to run this import.
      </p>
    )
  }

  if (commit.data) {
    return (
      <div className="mt-4" role="status">
        <p className="text-sm text-ink">
          Imported {commit.data.created_count} {commit.data.created_count === 1 ? 'item' : 'items'} from {sourceName}.
        </p>
        <Link
          to={`/projects/${projectId}/boq`}
          className="mt-2 inline-block rounded text-sm text-brand hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
        >
          Go to BOQ reconciliation
        </Link>
      </div>
    )
  }

  return (
    <div className="mt-4">
      {!extractionId && (
        <div>
          <div className="flex flex-wrap items-start gap-3">
            <label className="flex items-center gap-2 text-sm text-ink">
              <input type="checkbox" checked={useAi} onChange={(e) => setUseAi(e.target.checked)} />
              Use AI to read unclear or scanned pages
            </label>
            <AiStatusNotice />
          </div>
          {useAi && aiUnavailable && (
            <p className="mt-2 text-sm text-ink-2">
              AI is not available, so unclear or scanned pages will not be read. Only pages with a clear table are
              imported.
            </p>
          )}
          <div className="mt-3">
            <Button
              loading={start.isPending}
              disabled={!file && !documentId}
              onClick={() =>
                start.mutate(
                  { file, documentId: file ? null : documentId, useAi },
                  { onSuccess: (out) => setExtractionId(out.id) },
                )
              }
            >
              Read the PDF
            </Button>
          </div>
          {start.isError && (
            <p role="alert" className="mt-2 text-sm text-danger">
              {start.error.message}
            </p>
          )}
        </div>
      )}

      {extractionId && query.isError && (
        <p role="alert" className="text-sm text-danger">
          {query.error.message}
        </p>
      )}
      {extractionId && !extraction && !query.isError && <p className="text-sm text-ink-2">Loading extraction.</p>}

      {extraction && (
        <>
          <PdfExtractionProgress
            extraction={extraction}
            onRetry={() => retry.mutate()}
            retrying={retry.isPending}
            retryError={retry.isError ? retry.error.message : null}
          />
          {extraction.status === 'ready' && (
            <PdfRowsGrid
              extraction={extraction}
              onSave={(rows) => save.mutateAsync(rows)}
              onImport={() => commit.mutate()}
              saving={save.isPending}
              importing={commit.isPending}
              saveError={save.isError ? save.error.message : null}
              importError={commit.isError ? commit.error.message : null}
            />
          )}
          {extraction.status === 'committed' && (
            <p role="status" className="mt-3 text-sm text-ink">
              This extraction has already been imported.{' '}
              <Link to={`/projects/${projectId}/boq`} className="text-brand hover:underline">
                Go to BOQ reconciliation
              </Link>
            </p>
          )}
        </>
      )}
    </div>
  )
}
