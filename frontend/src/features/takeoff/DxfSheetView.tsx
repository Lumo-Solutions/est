import { useMemo } from 'react'
import type { DrawingEntityOut, DrawingMeasurementOut } from '../../types/api'
import { confidenceColor } from './confidence'
import { entitiesToSvgPaths } from './dxfGeometry'

interface Props {
  entities: DrawingEntityOut[]
  measurements: DrawingMeasurementOut[]
  selectedMeasurementId: string | null
  onSelectMeasurement: (id: string) => void
  /** When set, clicks on the sheet report a point in the sheet's own
   * native (un-flipped) coordinate space instead of selecting a
   * measurement -- used by the two-point calibration tool. */
  onPointClick?: (point: [number, number]) => void
}

function screenToSheetPoint(svg: SVGSVGElement, clientX: number, clientY: number): [number, number] {
  const point = svg.createSVGPoint()
  point.x = clientX
  point.y = clientY
  const ctm = svg.getScreenCTM()
  if (!ctm) return [0, 0]
  const transformed = point.matrixTransform(ctm.inverse())
  // Undo the render-time y-flip (DXF is y-up, SVG is y-down) to get back
  // to the sheet's own native coordinate space the backend expects.
  return [transformed.x, -transformed.y]
}

function hasBbox(
  m: DrawingMeasurementOut,
): m is DrawingMeasurementOut & { bbox_min_x: number; bbox_min_y: number; bbox_max_x: number; bbox_max_y: number } {
  return m.bbox_min_x != null && m.bbox_min_y != null && m.bbox_max_x != null && m.bbox_max_y != null
}

export function DxfSheetView({ entities, measurements, selectedMeasurementId, onSelectMeasurement, onPointClick }: Props) {
  const { paths, viewBox } = useMemo(() => entitiesToSvgPaths(entities), [entities])
  const viewBoxWidth = Number(viewBox.split(' ')[2]) || 100
  const strokeWidth = viewBoxWidth / 400

  return (
    <svg
      viewBox={viewBox}
      className={`h-full w-full bg-white ${onPointClick ? 'cursor-crosshair' : ''}`}
      preserveAspectRatio="xMidYMid meet"
      onClick={(e) => {
        if (!onPointClick) return
        onPointClick(screenToSheetPoint(e.currentTarget, e.clientX, e.clientY))
      }}
    >
      <g>
        {paths.map((p) => (
          <path key={p.id} d={p.d} stroke="#334155" fill="none" strokeWidth={strokeWidth} />
        ))}
      </g>
      <g>
        {measurements.filter(hasBbox).map((m) => {
          const x = m.bbox_min_x
          const y = -m.bbox_max_y
          const width = m.bbox_max_x - m.bbox_min_x
          const height = m.bbox_max_y - m.bbox_min_y
          const color = confidenceColor(m.confidence)
          const selected = m.id === selectedMeasurementId
          return (
            <rect
              key={m.id}
              x={x}
              y={y}
              width={Math.max(width, strokeWidth)}
              height={Math.max(height, strokeWidth)}
              stroke={color}
              fill={color}
              fillOpacity={selected ? 0.35 : 0.15}
              strokeWidth={selected ? strokeWidth * 2 : strokeWidth}
              onClick={() => onSelectMeasurement(m.id)}
              className="cursor-pointer"
            />
          )
        })}
      </g>
    </svg>
  )
}
