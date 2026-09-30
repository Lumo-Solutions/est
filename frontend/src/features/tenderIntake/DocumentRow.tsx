import { memo } from 'react'
import { Badge } from '../../components/Badge'
import { confidenceTone, flagLabel, formatConfidence } from './lib'
import { decidedByInfo, displayStatusLabel, displayStatusTone, folderSegments, formatUnitType, visibleFlags } from './treeLib'
import type { TreeItem } from './types'

export interface RowActions {
  onSelect: (id: string, selected: boolean) => void
  onView: (item: TreeItem) => void
  onChange: (item: TreeItem) => void
  onExclude: (item: TreeItem) => void
  onRerun: (item: TreeItem) => void
}

const actionClass =
  'rounded text-sm text-brand hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1'

function Chip({ children, title }: { children: React.ReactNode; title?: string }) {
  return (
    <span title={title} className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-ink-2">
      {children}
    </span>
  )
}

// One file in the tree. Memoised: the tree re-renders on every keystroke of the search box and on
// every poll, and only rows whose item or selection changed should repaint.
export const DocumentRow = memo(function DocumentRow({
  item,
  canAct,
  selected,
  showFolder,
  actions,
}: {
  item: TreeItem
  canAct: boolean
  selected: boolean
  showFolder: boolean
  actions: RowActions
}) {
  const decided = decidedByInfo(item)
  const isDrawing = item.doc_class === 'drawing'
  const folder = showFolder ? folderSegments(item.path).join('/') : ''
  const failed = item.display_status === 'failed'
  const checkable = item.display_status !== 'excluded'

  return (
    <li className="flex flex-wrap items-start gap-x-3 gap-y-1 py-2">
      {canAct && (
        <input
          type="checkbox"
          aria-label={`Select ${item.name}`}
          checked={selected}
          disabled={!checkable}
          onChange={(e) => actions.onSelect(item.id, e.target.checked)}
          className="mt-1 h-4 w-4 shrink-0 accent-brand"
        />
      )}
      <div className="min-w-0 flex-1 basis-64">
        <p className="truncate text-sm font-medium text-ink" title={item.path ?? item.name}>
          {item.name}
          {folder && <span className="ml-2 font-normal text-ink-2">{folder}</span>}
        </p>
        {isDrawing && (item.document_number || item.title || item.revision || item.sheet_number || item.scale || item.unit_type) && (
          <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-ink-2">
            {item.document_number && <Chip title="Drawing number">{item.document_number}</Chip>}
            {item.title && <span className="text-ink">{item.title}</span>}
            {item.revision && <Chip title="Revision">Rev {item.revision}</Chip>}
            {item.sheet_number && <Chip title="Sheet">Sheet {item.sheet_number}</Chip>}
            {item.scale && <Chip title="Scale">{item.scale}</Chip>}
            {item.unit_type && <Chip title="Unit type">{formatUnitType(item.unit_type)}</Chip>}
          </p>
        )}
        {item.supersedes.length > 0 && <p className="mt-0.5 text-xs text-ink-2">Supersedes: {item.supersedes.join(', ')}</p>}
        {(failed || item.display_status === 'needs_check') && item.status_reason && (
          <p className={`mt-0.5 text-xs ${failed ? 'text-danger' : 'text-ink-2'}`}>{item.status_reason}</p>
        )}
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-1.5">
        {item.confidence != null && (
          <Badge tone={confidenceTone(item.confidence)}>
            <span className="sr-only">Confidence </span>
            {formatConfidence(item.confidence)}
          </Badge>
        )}
        <span title={item.status_reason ?? undefined}>
          <Badge tone={displayStatusTone(item.display_status)}>{displayStatusLabel(item.display_status)}</Badge>
        </span>
        {decided && <Badge tone={decided.tone}>{decided.label}</Badge>}
        {visibleFlags(item).map(({ flag, tone }) => (
          <Badge key={flag} tone={tone}>
            {flagLabel(flag)}
          </Badge>
        ))}
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1">
        <button type="button" className={actionClass} aria-label={`View evidence for ${item.name}`} onClick={() => actions.onView(item)}>
          View evidence
        </button>
        {canAct && (
          <button type="button" className={actionClass} aria-label={`Change class of ${item.name}`} onClick={() => actions.onChange(item)}>
            Change class
          </button>
        )}
        <a href={`/api/v1/tender-documents/${item.id}/download`} className={actionClass} aria-label={`Download ${item.name}`}>
          Download
        </a>
        {canAct && item.display_status !== 'excluded' && (
          <button type="button" className={actionClass} aria-label={`Exclude ${item.name}`} onClick={() => actions.onExclude(item)}>
            Exclude
          </button>
        )}
        {canAct && failed && (
          <button type="button" className={actionClass} aria-label={`Re-run ${item.name}`} onClick={() => actions.onRerun(item)}>
            Re-run
          </button>
        )}
      </div>
    </li>
  )
})
