import { memo, useMemo, useState } from 'react'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Card, SectionHeading } from '../../components/Card'
import { ConfirmModal } from '../../components/ConfirmModal'
import { ClassFields } from './ClassFields'
import { EMPTY_CHOICE, choiceBody, type ClassChoice } from './classChoice'
import { useBulkConfirm, useConfirmDocument, useReclassifyDocument, useTenderClasses } from './api'
import { confidenceTone, disciplineLabel, drawingTypeLabel, flagLabel, formatConfidence } from './lib'
import { classLabeler, classOptions, decidedByInfo, isBulkConfirmable, needsCheckItems, visibleFlags } from './treeLib'
import type { TreeItem } from './types'

const PAGE = 25
const msg = (e: unknown) => (e instanceof Error ? e.message : 'Request failed')

interface RowProps {
  item: TreeItem
  canAct: boolean
  classLabel: (code: string) => string
  options: ReturnType<typeof classOptions>
  busy: boolean
  error: string | null
  onConfirm: (item: TreeItem) => void
  onChange: (item: TreeItem, body: ReturnType<typeof choiceBody>) => void
}

const Row = memo(function Row({ item, canAct, classLabel, options, busy, error, onConfirm, onChange }: RowProps) {
  const [editing, setEditing] = useState(false)
  const [showEvidence, setShowEvidence] = useState(false)
  const [choice, setChoice] = useState<ClassChoice>(EMPTY_CHOICE)
  const folder = item.path?.includes('/') ? item.path.slice(0, item.path.lastIndexOf('/')) : null
  const decided = decidedByInfo(item)
  const hasEvidence = Boolean(item.evidence_quote || item.ai_note)

  const pick = (next: ClassChoice) => {
    setChoice(next)
    // A non-drawing class is a complete answer, so choosing it applies at once; a drawing still
    // needs its discipline and type, so it waits for Apply.
    if (next.doc_class && next.doc_class !== 'drawing') {
      setEditing(false)
      onChange(item, choiceBody(next))
    }
  }

  return (
    <li className="py-3">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1">
          <p className="truncate text-base font-medium text-ink" title={item.path ?? item.name}>
            {item.name}
            {folder && <span className="ml-2 text-sm font-normal text-ink-2">{folder}</span>}
          </p>
          <p className="mt-0.5 flex flex-wrap items-center gap-2 text-sm text-ink">
            <span>
              Proposed:{' '}
              <strong className="font-semibold">{item.doc_class ? classLabel(item.doc_class) : 'No class proposed'}</strong>
              {item.doc_class === 'drawing' && (item.discipline || item.drawing_type) && (
                <span className="text-ink-2">
                  {' '}
                  ({[item.discipline && disciplineLabel(item.discipline), item.drawing_type && drawingTypeLabel(item.drawing_type)]
                    .filter(Boolean)
                    .join(', ')}
                  )
                </span>
              )}
            </span>
            {item.confidence != null && (
              <Badge tone={confidenceTone(item.confidence)}>{formatConfidence(item.confidence)} sure</Badge>
            )}
            {decided && <Badge tone={decided.tone}>{decided.label}</Badge>}
            {visibleFlags(item).map(({ flag, tone }) => (
              <Badge key={flag} tone={tone}>
                {flagLabel(flag)}
              </Badge>
            ))}
          </p>
          {item.status_reason && <p className="mt-0.5 text-sm text-ink-2">{item.status_reason}</p>}
          {hasEvidence && (
            <div className="mt-1">
              <button
                type="button"
                aria-expanded={showEvidence}
                onClick={() => setShowEvidence((v) => !v)}
                className="rounded text-sm text-brand hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
              >
                {showEvidence ? 'Hide evidence' : 'Show evidence'}
                <span className="sr-only"> for {item.name}</span>
              </button>
              {showEvidence && (
                <blockquote className="mt-1 border-l-2 border-hairline pl-3 text-sm text-ink-2">
                  {item.evidence_quote && (
                    <p>
                      &ldquo;{item.evidence_quote}&rdquo;
                      {item.evidence_page != null && ` (page ${item.evidence_page})`}
                    </p>
                  )}
                  {item.ai_note && <p>{item.ai_note}</p>}
                </blockquote>
              )}
            </div>
          )}
        </div>
        {canAct && (
          <div className="flex shrink-0 items-center gap-2">
            <Button size="sm" loading={busy} onClick={() => onConfirm(item)} aria-label={`Confirm ${item.name}`}>
              Confirm
            </Button>
            <Button
              size="sm"
              variant="secondary"
              disabled={busy}
              aria-expanded={editing}
              aria-label={`Change class of ${item.name}`}
              onClick={() => setEditing((v) => !v)}
            >
              Change
            </Button>
          </div>
        )}
      </div>
      {canAct && editing && (
        <div className="mt-2 flex flex-wrap items-end gap-2">
          <ClassFields compact options={options} value={choice} onChange={pick} placeholder="Choose class..." />
          {choice.doc_class === 'drawing' && (
            <Button
              size="sm"
              onClick={() => {
                setEditing(false)
                onChange(item, choiceBody(choice))
              }}
            >
              Apply as drawing
            </Button>
          )}
        </div>
      )}
      {error && (
        <p role="alert" className="mt-1 text-sm text-danger">
          {error}
        </p>
      )}
    </li>
  )
})

// The "Needs your check" list at the top of the project page: one-click Confirm or Change for each
// file the AI was not sure enough about to route on its own.
export function NeedsCheckList({ projectId, items, canConfirm }: { projectId: string; items: TreeItem[]; canConfirm: boolean }) {
  const { data: classes = [] } = useTenderClasses()
  const confirmDoc = useConfirmDocument(projectId)
  const reclassify = useReclassifyDocument(projectId)
  const bulk = useBulkConfirm(projectId)
  const [limit, setLimit] = useState(PAGE)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [confirmAll, setConfirmAll] = useState(false)
  const [result, setResult] = useState<string | null>(null)
  const [failures, setFailures] = useState<string[]>([])

  const rows = useMemo(() => needsCheckItems(items), [items])
  const shown = rows.slice(0, limit)
  const bulkIds = useMemo(() => shown.filter(isBulkConfirmable).map((i) => i.id), [shown])
  const classLabel = useMemo(() => classLabeler(classes), [classes])
  const options = useMemo(() => classOptions(classes), [classes])
  const nameOf = useMemo(() => new Map(rows.map((r) => [r.id, r.name])), [rows])

  if (rows.length === 0) return null

  const setError = (id: string, m: string | null) =>
    setErrors((prev) => {
      const next = { ...prev }
      if (m) next[id] = m
      else delete next[id]
      return next
    })

  const onConfirm = (item: TreeItem) => {
    setBusyId(item.id)
    setError(item.id, null)
    confirmDoc.mutate(item.id, {
      onError: (e) => setError(item.id, `Could not confirm ${item.name}: ${msg(e)}`),
      onSettled: () => setBusyId(null),
    })
  }

  const onChange = (item: TreeItem, body: ReturnType<typeof choiceBody>) => {
    setBusyId(item.id)
    setError(item.id, null)
    reclassify.mutate(
      { id: item.id, ...body, confirm: true },
      {
        onError: (e) => setError(item.id, `Could not change ${item.name}: ${msg(e)}`),
        onSettled: () => setBusyId(null),
      },
    )
  }

  const runConfirmAll = () => {
    setConfirmAll(false)
    setResult(null)
    setFailures([])
    bulk.mutate(
      { document_ids: bulkIds },
      {
        onSuccess: (r) => {
          setResult(`Confirmed ${r.confirmed}, skipped ${r.skipped}, failed ${r.failed}`)
          setFailures(r.results.filter((x) => !x.ok && x.error).map((x) => `${nameOf.get(x.id) ?? x.id}: ${x.error}`))
        },
        onError: (e) => setFailures([msg(e)]),
      },
    )
  }

  const heldBack = shown.length - bulkIds.length

  return (
    <Card className="mt-6 border-2 border-warning-subtle">
      <SectionHeading
        action={
          canConfirm && bulkIds.length > 0 ? (
            <Button size="sm" loading={bulk.isPending} onClick={() => setConfirmAll(true)}>
              Confirm all shown ({bulkIds.length})
            </Button>
          ) : undefined
        }
      >
        Needs your check ({rows.length})
      </SectionHeading>
      <p className="mb-2 text-sm text-ink-2">
        {canConfirm
          ? 'These files were not certain enough to sort on their own. Confirm the proposed class or change it.'
          : 'These files need a lead estimator or above to confirm or change the class. You can see them here but not change them.'}
      </p>
      {result && (
        <p role="status" className="mb-2 text-sm text-ink">
          {result}
        </p>
      )}
      {failures.length > 0 && (
        <ul role="alert" className="mb-2 space-y-1 text-sm text-danger">
          {failures.map((f) => (
            <li key={f}>{f}</li>
          ))}
        </ul>
      )}
      <ul aria-label="Files that need your check" className="divide-y divide-row-rule">
        {shown.map((item) => (
          <Row
            key={item.id}
            item={item}
            canAct={canConfirm}
            classLabel={classLabel}
            options={options}
            busy={busyId === item.id}
            error={errors[item.id] ?? null}
            onConfirm={onConfirm}
            onChange={onChange}
          />
        ))}
      </ul>
      {rows.length > shown.length && (
        <div className="mt-3">
          <Button variant="secondary" size="sm" onClick={() => setLimit((l) => l + PAGE)}>
            Show {Math.min(PAGE, rows.length - shown.length)} more ({rows.length - shown.length} not shown)
          </Button>
        </div>
      )}
      <ConfirmModal
        open={confirmAll}
        title="Confirm all shown?"
        message={`Route ${bulkIds.length} ${bulkIds.length === 1 ? 'file' : 'files'} as proposed.${
          heldBack > 0 ? ` ${heldBack} with a conflict or suspicious text stay here for a one-by-one check.` : ''
        }`}
        confirmLabel="Confirm all"
        onCancel={() => setConfirmAll(false)}
        onConfirm={runConfirmAll}
      />
    </Card>
  )
}
