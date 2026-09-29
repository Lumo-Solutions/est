import { Modal } from '../../components/Modal'
import { SkeletonRows } from '../../components/Skeleton'
import { Button } from '../../components/Button'
import { useTenderDocument } from './api'
import { formatConfidence } from './lib'
import type { TenderClass } from './types'

const SOURCE_LABEL: Record<string, string> = { rules: 'Rules', model: 'Model', user: 'User' }

function show(v: unknown): string {
  if (v == null || v === '') return '--'
  return typeof v === 'object' ? JSON.stringify(v) : String(v)
}

export function EvidenceModal({
  documentId,
  filename,
  classes,
  onClose,
}: {
  documentId: string | null
  filename: string
  classes: TenderClass[]
  onClose: () => void
}) {
  const { data, isLoading, isError, error } = useTenderDocument(documentId ?? undefined)
  const classLabel = (code: string) => classes.find((c) => c.code === code)?.label ?? code

  return (
    <Modal open={documentId !== null} title={`Evidence for ${filename}`} onClose={onClose}>
      <div className="mt-3 max-h-[60vh] space-y-4 overflow-y-auto pr-1 text-sm text-ink">
        {isLoading && <SkeletonRows count={3} />}
        {isError && (
          <p role="alert" className="text-danger">
            {error.message}
          </p>
        )}
        {data && data.classifications.length === 0 && <p className="text-ink-2">No classification history yet.</p>}
        {data?.classifications.map((c) => (
          <section key={c.id} aria-label={`${SOURCE_LABEL[c.source] ?? c.source} classification`}>
            <p className="font-medium">
              {SOURCE_LABEL[c.source] ?? c.source}: {classLabel(c.doc_class)}
              {c.sub_type ? ` (${c.sub_type})` : ''} at {formatConfidence(c.confidence)}
              {c.is_current ? ' (current)' : ''}
            </p>
            {c.evidence.length > 0 && (
              <ul className="mt-1 space-y-1 text-ink-2">
                {c.evidence.map((e, i) => (
                  <li key={i}>
                    Rule {show(e.rule)}: &ldquo;{show(e.matched ?? e.text)}&rdquo; (page {show(e.page)})
                  </li>
                ))}
              </ul>
            )}
            {Object.keys(c.metadata ?? {}).length > 0 && (
              <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 text-ink-2">
                {Object.entries(c.metadata).map(([k, v]) => (
                  <div key={k} className="contents">
                    <dt className="font-medium">{k}:</dt>
                    <dd>{show(v)}</dd>
                  </div>
                ))}
              </dl>
            )}
          </section>
        ))}
      </div>
      <div className="mt-3 flex justify-end">
        <Button variant="secondary" size="sm" onClick={onClose}>
          Close
        </Button>
      </div>
    </Modal>
  )
}
