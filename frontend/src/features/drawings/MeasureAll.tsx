import { useState } from 'react'
import { useAuth } from '../../auth/AuthContext'
import { Button } from '../../components/Button'
import { Card, SectionHeading } from '../../components/Card'
import { Role } from '../../lib/roles'
import { disciplineLabel } from '../tenderIntake/lib'
import type { MeasureOut, MeasurementState } from '../../types/api'
import { useMeasureDrawings, useMeasurementSummary } from './api'

const MEASURE_ROLES = [Role.LEAD_ESTIMATOR, Role.PROCUREMENT_HEAD, Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR]

const COUNT_LABELS: [MeasurementState, string][] = [
  ['indexed', 'Not measured'],
  ['queued', 'Queued'],
  ['measuring', 'Measuring'],
  ['measured', 'Measured'],
  ['failed', 'Failed'],
]

// Drawings are only classified and indexed at intake; this card shows where each stands and lets a lead start
// measuring a whole discipline at once.
export function MeasureAll({ projectId }: { projectId: string }) {
  const { hasRole } = useAuth()
  const canMeasure = hasRole(...MEASURE_ROLES)
  const summary = useMeasurementSummary(projectId)
  const measure = useMeasureDrawings(projectId)
  const [chosen, setChosen] = useState<Set<string>>(new Set())
  const [result, setResult] = useState<MeasureOut | null>(null)

  const data = summary.data
  if (!data) return null
  const all = Object.values(data.total).reduce((a, b) => a + b, 0)
  if (all === 0) return null

  const choices = Object.entries(data.by_discipline)
    .filter(([, c]) => c.indexed + c.failed > 0)
    .map(([code, c]) => ({ code, count: c.indexed + c.failed }))
  const selected = choices.filter((c) => chosen.has(c.code)).map((c) => c.code)

  function toggle(code: string) {
    setChosen((prev) => {
      const next = new Set(prev)
      if (next.has(code)) next.delete(code)
      else next.add(code)
      return next
    })
  }

  function start() {
    measure.mutate({ disciplines: selected }, { onSuccess: (r) => setResult(r) })
  }

  return (
    <Card className="mt-6" aria-labelledby="measure-all-heading">
      <SectionHeading>
        <span id="measure-all-heading">Drawings to measure</span>
      </SectionHeading>
      <p className="text-sm text-muted">
        Drawings are measured when you open them, or all at once here. Measuring reads the sheets and can take a while.
      </p>
      <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-2 text-sm" data-testid="measure-counts">
        {COUNT_LABELS.map(([state, label]) => (
          <div key={state} className="flex items-baseline gap-1.5">
            <dt className="text-muted">{label}</dt>
            <dd className="font-medium tabular-nums text-ink">{data.total[state] ?? 0}</dd>
          </div>
        ))}
      </dl>
      {canMeasure && choices.length > 0 && (
        <fieldset className="mt-4">
          <legend className="text-sm font-medium text-ink">Disciplines to measure</legend>
          <div className="mt-2 flex flex-wrap gap-x-5 gap-y-2">
            {choices.map((c) => (
              <label key={c.code} className="flex items-center gap-2 text-sm text-ink">
                <input type="checkbox" checked={chosen.has(c.code)} onChange={() => toggle(c.code)} />
                {disciplineLabel(c.code)} ({c.count})
              </label>
            ))}
          </div>
        </fieldset>
      )}
      {canMeasure && choices.length > 0 && (
        <div className="mt-4">
          <Button size="sm" onClick={start} loading={measure.isPending} disabled={selected.length === 0}>
            Measure selected
          </Button>
        </div>
      )}
      {result && (
        <p role="status" className="mt-3 text-sm text-ink">
          Queued {result.queued} drawings ({result.measured + result.measuring} already measured or running)
        </p>
      )}
      {measure.isError && (
        <p role="alert" className="mt-3 text-sm text-danger">
          {measure.error.message}
        </p>
      )}
      {(data.total.queued > 0 || data.total.measuring > 0) && (
        <p role="status" className="mt-3 text-sm text-muted">
          Measuring in progress: {data.total.measuring} running, {data.total.queued} waiting.
        </p>
      )}
    </Card>
  )
}
