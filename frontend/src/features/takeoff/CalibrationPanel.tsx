import { useState } from 'react'
import { useRevertScaleCalibration, useScaleCalibrations, useSetManualScale } from '../drawings/api'

interface Props {
  drawingId: string
  sheetIndex: number
  calibrating: boolean
  onCalibratingChange: (calibrating: boolean) => void
  points: [number, number][]
  onResetPoints: () => void
}

export function CalibrationPanel({ drawingId, sheetIndex, calibrating, onCalibratingChange, points, onResetPoints }: Props) {
  const [knownLength, setKnownLength] = useState('')
  const { data: history } = useScaleCalibrations(drawingId, sheetIndex)
  const setScale = useSetManualScale(drawingId, sheetIndex)
  const revert = useRevertScaleCalibration(drawingId, sheetIndex)

  return (
    <div className="border-t border-slate-200 p-4">
      <h3 className="text-sm font-semibold text-slate-800">Two-point calibration</h3>
      <button
        type="button"
        onClick={() => {
          onResetPoints()
          onCalibratingChange(!calibrating)
        }}
        className="mt-2 rounded border border-slate-300 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50"
      >
        {calibrating ? 'Cancel' : 'Pick two points on the drawing'}
      </button>

      {calibrating && points.length < 2 && (
        <p className="mt-2 text-xs text-slate-500">
          Click point {points.length + 1} of 2 on the drawing.
        </p>
      )}

      {points.length === 2 && (
        <form
          className="mt-2 flex items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            setScale.mutate(
              { p1: points[0], p2: points[1], known_length_m: Number(knownLength) },
              {
                onSuccess: () => {
                  onResetPoints()
                  onCalibratingChange(false)
                  setKnownLength('')
                },
              },
            )
          }}
        >
          <div>
            <label className="block text-xs text-slate-500" htmlFor="known-length">
              Known length (m)
            </label>
            <input
              id="known-length"
              type="number"
              step="any"
              required
              value={knownLength}
              onChange={(e) => setKnownLength(e.target.value)}
              className="w-28 rounded border border-slate-300 px-2 py-1 text-sm"
            />
          </div>
          <button
            type="submit"
            disabled={setScale.isPending}
            className="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
          >
            Set scale
          </button>
        </form>
      )}
      {setScale.isError && <p className="mt-1 text-sm text-red-600">{setScale.error.message}</p>}

      {history && history.length > 0 && (
        <table className="mt-3 w-full text-left text-xs">
          <thead className="text-slate-500">
            <tr>
              <th>Ratio</th>
              <th>Source</th>
              <th>Confidence</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {history.map((c) => (
              <tr key={c.id} className="border-t border-slate-100">
                <td>{c.ratio?.toFixed(6) ?? '--'}</td>
                <td>{c.source}</td>
                <td>{(c.confidence * 100).toFixed(0)}%</td>
                <td>
                  <button
                    type="button"
                    onClick={() => revert.mutate(c.id)}
                    className="text-slate-500 underline hover:text-slate-800"
                  >
                    Revert to this
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
