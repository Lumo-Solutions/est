import { memo, useMemo, useRef, useState } from 'react'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { Card, SectionHeading } from '../../components/Card'
import { ConfirmModal } from '../../components/ConfirmModal'
import { ClassFields } from './ClassFields'
import { EMPTY_CHOICE, choiceBody, type ClassChoice } from './classChoice'
import { useBulkConfirm, useConfirmDocument, useInvalidateIntake, useReclassifyDocument, useTenderClasses, useTenderItems } from './api'
import { confidenceTone, disciplineLabel, drawingTypeLabel, formatConfidence } from './lib'
import { CONFIRM_ALL_FILTER, NEEDS_CHECK_FILTER, capList, classLabeler, classOptions, decidedByInfo, flagText, visibleFlags } from './treeLib'
import type { TreeItem, TreeSummary } from './types'

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
                {flagText(flag)}
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
            {item.doc_class && (
              <Button size="sm" loading={busy} onClick={() => onConfirm(item)} aria-label={`Confirm ${item.name}`}>
                Confirm
              </Button>
            )}
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


// The "Needs your check" list at the top of the project page: one-click Confirm or Change for each file the AI was
// not sure enough about to route on its own. The list is paged from the server; "Confirm all" works server-side on
// every matching file, not just the rows on screen.
export function NeedsCheckList({ projectId, summary, canConfirm }: { projectId: string; summary: TreeSummary; canConfirm: boolean }) {
  const { data: classes = [] } = useTenderClasses()
  const confirmDoc = useConfirmDocument(projectId)
  const reclassify = useReclassifyDocument(projectId)
  const bulk = useBulkConfirm(projectId, { quiet: true })
  const invalidateIntake = useInvalidateIntake(projectId)
  const list = useTenderItems(projectId, NEEDS_CHECK_FILTER, { limit: PAGE, enabled: summary.needs_check > 0 })
  const confirmable = useTenderItems(projectId, CONFIRM_ALL_FILTER, { limit: 1, enabled: canConfirm && summary.needs_check > 0 })
  const [busyId, setBusyId] = useState<string | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [confirmAll, setConfirmAll] = useState(false)
  const [running, setRunning] = useState(false)
  const [progress, setProgress] = useState<{ confirmed: number; total: number } | null>(null)
  const [result, setResult] = useState<string | null>(null)
  const [failures, setFailures] = useState<string[]>([])
  const cancelRef = useRef(false)

  const rows = useMemo(() => list.data?.pages.flatMap((p) => p.items) ?? [], [list.data])
  const classLabel = useMemo(() => classLabeler(classes), [classes])
  const options = useMemo(() => classOptions(classes), [classes])

  if (summary.needs_check === 0 && !running && !result) return null

  const confirmableCount = confirmable.data?.pages[0]?.total ?? 0
  const heldBack = Math.max(0, summary.needs_check - confirmableCount)

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

  // Confirm every matching file: one chunk per request, following next_cursor until the server says it is done.
  const runConfirmAll = async () => {
    setConfirmAll(false)
    setResult(null)
    setFailures([])
    setRunning(true)
    cancelRef.current = false
    const names = new Map(rows.map((r) => [r.id, r.name]))
    let total = confirmableCount
    let confirmed = 0
    let failed = 0
    let skipped = 0
    let stopped = false
    const fails: string[] = []
    setProgress({ confirmed, total })
    try {
      let cursor: string | null = null
      let first = true
      do {
        if (cancelRef.current) {
          stopped = true
          break
        }
        const r: Awaited<ReturnType<typeof bulk.mutateAsync>> = await bulk.mutateAsync({ filter: CONFIRM_ALL_FILTER, cursor })
        if (first && r.matched != null) total = r.matched
        first = false
        confirmed += r.confirmed
        failed += r.failed
        skipped += r.skipped
        for (const x of r.results) if (!x.ok && x.error) fails.push(`${names.get(x.id) ?? x.id}: ${x.error}`)
        setProgress({ confirmed, total })
        const next: string | null = r.next_cursor ?? null
        if (next === cursor) break
        cursor = next
      } while (cursor)
    } catch (e) {
      fails.push(msg(e))
    } finally {
      setRunning(false)
      setProgress(null)
      invalidateIntake()
    }
    setResult(
      `${stopped ? 'Stopped. ' : ''}Confirmed ${confirmed} of ${total}${skipped > 0 ? `, skipped ${skipped}` : ''}${failed > 0 ? `, failed ${failed}` : ''}`,
    )
    setFailures(fails)
  }

  const failureView = capList(failures, 20)
  const notShown = summary.needs_check - rows.length

  return (
    <Card className="mt-6 border-2 border-warning-subtle">
      <SectionHeading
        action={
          canConfirm && confirmableCount > 0 && !running ? (
            <Button size="sm" onClick={() => setConfirmAll(true)}>
              Confirm all ({confirmableCount})
            </Button>
          ) : undefined
        }
      >
        Needs your check ({summary.needs_check})
      </SectionHeading>
      <p className="mb-2 text-sm text-ink-2">
        {canConfirm
          ? 'These files were not certain enough to sort on their own. Confirm the proposed class or change it.'
          : 'These files need a lead estimator or above to confirm or change the class. You can see them here but not change them.'}
      </p>
      {progress && (
        <div className="mb-2 flex flex-wrap items-center gap-3">
          <p role="status" className="text-sm text-ink">
            Confirmed {progress.confirmed} of {progress.total}
          </p>
          <Button variant="secondary" size="sm" onClick={() => (cancelRef.current = true)}>
            Cancel
          </Button>
        </div>
      )}
      {result && (
        <p role="status" className="mb-2 text-sm text-ink">
          {result}
        </p>
      )}
      {failureView.shown.length > 0 && (
        <ul role="alert" className="mb-2 space-y-1 text-sm text-danger">
          {failureView.shown.map((f, i) => (
            <li key={`${i}-${f}`}>{f}</li>
          ))}
          {failureView.more > 0 && <li>and {failureView.more} more</li>}
        </ul>
      )}
      {list.isError && (
        <p role="alert" className="mb-2 text-sm text-danger">
          {msg(list.error)}
        </p>
      )}
      <ul aria-label="Files that need your check" className="divide-y divide-row-rule">
        {rows.map((item) => (
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
      {list.hasNextPage && (
        <div className="mt-3">
          <Button variant="secondary" size="sm" loading={list.isFetchingNextPage} onClick={() => void list.fetchNextPage()}>
            Show {Math.min(PAGE, Math.max(notShown, 0)) || PAGE} more{notShown > 0 ? ` (${notShown} not shown)` : ''}
          </Button>
        </div>
      )}
      <ConfirmModal
        open={confirmAll}
        title="Confirm all?"
        message={`Route ${confirmableCount} ${confirmableCount === 1 ? 'file' : 'files'} as proposed.${
          heldBack > 0 ? ` ${heldBack} stay here for a one-by-one check (a conflict, suspicious text or no proposed class).` : ''
        }`}
        confirmLabel="Confirm all"
        onCancel={() => setConfirmAll(false)}
        onConfirm={() => void runConfirmAll()}
      />
    </Card>
  )
}
