import { useState } from 'react'
import { useOverrideMeasurement, useRevertMeasurementOverride } from '../drawings/api'
import { confidenceBand } from './confidence'
import type { DrawingMeasurementOut } from '../../types/api'

const BAND_LABEL: Record<string, string> = {
  high: 'High confidence',
  medium: 'Medium confidence',
  low: 'Low confidence -- review recommended',
}

export function MeasurementPanel({
  measurement,
  drawingId,
  sheetId,
}: {
  measurement: DrawingMeasurementOut
  drawingId: string
  sheetId: string
}) {
  const [value, setValue] = useState(String(measurement.effective_value))
  const [unit, setUnit] = useState(measurement.unit)
  const [note, setNote] = useState('')
  const override = useOverrideMeasurement(drawingId, sheetId)
  const revert = useRevertMeasurementOverride(drawingId, sheetId)
  const isOverridden = measurement.effective_value !== measurement.value

  return (
    <div className="border-t border-hairline p-4">
      <h3 className="text-lg font-semibold text-ink-title">
        {measurement.capability} / {measurement.kind}
      </h3>
      <p className="mt-1 text-sm text-ink-2">
        Raw: {measurement.value} {measurement.unit}
        {isOverridden && (
          <span className="ml-2 text-ink">
            → Effective: {measurement.effective_value} {measurement.unit}
          </span>
        )}
      </p>
      <p className="mt-1 text-xs text-muted">
        {BAND_LABEL[confidenceBand(measurement.confidence)]} ({(measurement.confidence * 100).toFixed(0)}%)
      </p>

      {isOverridden && (
        <button
          type="button"
          onClick={() => revert.mutate(measurement.id)}
          disabled={revert.isPending}
          className="mt-2 rounded-pill border border-brand px-2 py-1 text-xs text-brand hover:bg-brand-subtle"
        >
          Revert to raw value
        </button>
      )}

      <form
        className="mt-3 flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          override.mutate(
            { measurementId: measurement.id, value: Number(value), unit, note },
            { onSuccess: () => setNote('') },
          )
        }}
      >
        <div>
          <label className="mb-1 block text-sm text-ink" htmlFor="override-value">
            Override value
          </label>
          <input
            id="override-value"
            type="number"
            step="any"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className="w-24 rounded border border-outline px-2 py-1 text-sm"
          />
        </div>
        <div>
          <label className="mb-1 block text-sm text-ink" htmlFor="override-unit">
            Unit
          </label>
          <input
            id="override-unit"
            value={unit}
            onChange={(e) => setUnit(e.target.value)}
            className="w-16 rounded border border-outline px-2 py-1 text-sm"
          />
        </div>
        <div className="flex-1">
          <label className="mb-1 block text-sm text-ink" htmlFor="override-note">
            Note (why)
          </label>
          <input
            id="override-note"
            required
            value={note}
            onChange={(e) => setNote(e.target.value)}
            className="w-full rounded border border-outline px-2 py-1 text-sm"
          />
        </div>
        <button
          type="submit"
          disabled={override.isPending}
          className="rounded-control bg-brand px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 hover:bg-brand-hover"
        >
          Override
        </button>
      </form>
      {override.isError && <p className="mt-1 text-sm text-red-600">{override.error.message}</p>}
    </div>
  )
}
