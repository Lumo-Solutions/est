import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Card, SectionHeading } from '../../components/Card'
import { controlClasses } from '../../components/Field'
import type { TreeSummary } from './types'

const linkButton =
  'inline-flex items-center justify-center rounded-control bg-brand px-4 py-1.5 text-sm font-medium text-white transition-colors duration-150 hover:bg-brand-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2'
const disabledButton =
  'inline-flex cursor-not-allowed items-center justify-center rounded-control bg-brand px-4 py-1.5 text-sm font-medium text-white opacity-50'

function Step({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <li className="flex flex-col gap-2 rounded-card border border-hairline p-4">
      <h3 className="text-base font-semibold text-ink-title">{title}</h3>
      {children}
    </li>
  )
}

// What to do once documents are in: import the BOQ, measure the drawings, verify, settle. Disabled
// steps say why in text.
export function NextSteps({ projectId, summary }: { projectId: string; summary: TreeSummary }) {
  const boqDocs = summary.boq_documents
  const [pickedBoq, setPickedBoq] = useState('')
  const boqId = boqDocs.some((d) => d.id === pickedBoq) ? pickedBoq : (boqDocs[0]?.id ?? '')
  const nameOf = (id: string) => boqDocs.find((d) => d.id === id)?.name ?? id
  const firstDrawingId = summary.first_drawing_id

  return (
    <Card className="mt-6">
      <SectionHeading>Next steps</SectionHeading>
      <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Step title="Import BOQ">
          {boqDocs.length > 1 && (
            <div>
              <label htmlFor="next-boq" className="mb-1 block text-xs text-ink-2">
                BOQ document
              </label>
              <select id="next-boq" value={boqId} onChange={(e) => setPickedBoq(e.target.value)} className={`${controlClasses} !py-1.5 !text-sm`}>
                {boqDocs.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </div>
          )}
          {boqId ? (
            <>
              <p className="text-sm text-ink-2">
                {boqDocs.length === 1 ? `${nameOf(boqId)} is ready to import.` : `${boqDocs.length} BOQ documents are ready to import.`}
              </p>
              <Link to={`/projects/${projectId}/boq/import?document=${boqId}`} className={`${linkButton} self-start`}>
                Import BOQ
              </Link>
            </>
          ) : (
            <>
              <p id="next-boq-why" className="text-sm text-ink-2">
                No BOQ has been found yet. It appears here once a BOQ file is classified and ready.
              </p>
              <span role="link" aria-disabled="true" aria-describedby="next-boq-why" className={`${disabledButton} self-start`}>
                Import BOQ
              </span>
            </>
          )}
        </Step>
        <Step title="Open drawings / takeoff">
          <p className="text-sm text-ink-2">
            {summary.drawings_ready} of {summary.drawings_total} drawings ready
          </p>
          {firstDrawingId ? (
            <Link to={`/projects/${projectId}/drawings/${firstDrawingId}`} className={`${linkButton} self-start`}>
              Open drawings / takeoff
            </Link>
          ) : (
            <>
              <p id="next-drawings-why" className="text-sm text-ink-2">
                {summary.drawings_total > 0 ? 'Drawings are still being prepared.' : 'No drawings yet.'}
              </p>
              <span role="link" aria-disabled="true" aria-describedby="next-drawings-why" className={`${disabledButton} self-start`}>
                Open drawings / takeoff
              </span>
            </>
          )}
        </Step>
        <Step title="Run verification report">
          <p className="text-sm text-ink-2">Check the takeoff against the BOQ.</p>
          <Link to={`/projects/${projectId}/verification`} className={`${linkButton} self-start`}>
            Run verification report
          </Link>
        </Step>
        <Step title="Build settlement">
          <p className="text-sm text-ink-2">Turn verified quantities into a settlement.</p>
          <Link to={`/projects/${projectId}/settlement`} className={`${linkButton} self-start`}>
            Build settlement
          </Link>
        </Step>
      </ul>
    </Card>
  )
}
