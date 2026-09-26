import * as pdfjsLib from 'pdfjs-dist'
import type { PDFPageProxy } from 'pdfjs-dist'
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { useEffect, useRef, useState } from 'react'
import type { DrawingMeasurementOut } from '../../types/api'
import { confidenceColor } from './confidence'

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl

interface Props {
  downloadUrl: string
  pageNumber: number
  measurements: DrawingMeasurementOut[]
  selectedMeasurementId: string | null
  onSelectMeasurement: (id: string) => void
  /** When set, clicks on the page report a point in the PDF's own native
   * (points) coordinate space -- used by the two-point calibration tool. */
  onPointClick?: (point: [number, number]) => void
}

function hasBbox(
  m: DrawingMeasurementOut,
): m is DrawingMeasurementOut & { bbox_min_x: number; bbox_min_y: number; bbox_max_x: number; bbox_max_y: number } {
  return m.bbox_min_x != null && m.bbox_min_y != null && m.bbox_max_x != null && m.bbox_max_y != null
}

export function PdfSheetView({
  downloadUrl,
  pageNumber,
  measurements,
  selectedMeasurementId,
  onSelectMeasurement,
  onPointClick,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const overlayRef = useRef<SVGSVGElement>(null)
  const [viewport, setViewport] = useState<{ width: number; height: number } | null>(null)
  const [page, setPage] = useState<PDFPageProxy | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const loadingTask = pdfjsLib.getDocument({ url: downloadUrl })

    loadingTask.promise
      .then((loaded) => loaded.getPage(pageNumber))
      .then(async (loadedPage) => {
        if (cancelled) return
        const canvas = canvasRef.current
        if (!canvas) return
        const scale = 1.5
        const pdfViewport = loadedPage.getViewport({ scale })
        canvas.width = pdfViewport.width
        canvas.height = pdfViewport.height
        const context = canvas.getContext('2d')
        if (!context) return
        await loadedPage.render({ canvasContext: context, viewport: pdfViewport, canvas }).promise
        if (cancelled) return
        setPage(loadedPage)
        setViewport({ width: pdfViewport.width, height: pdfViewport.height })
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      })

    return () => {
      cancelled = true
      loadingTask.destroy()
    }
  }, [downloadUrl, pageNumber])

  if (error) return <p className="p-4 text-red-600">Failed to render PDF: {error}</p>

  return (
    <div className="relative inline-block">
      <canvas ref={canvasRef} />
      {page && viewport && (
        <svg
          ref={overlayRef}
          className={`absolute left-0 top-0 ${onPointClick ? 'cursor-crosshair' : ''}`}
          width={viewport.width}
          height={viewport.height}
          viewBox={`0 0 ${viewport.width} ${viewport.height}`}
          onClick={(e) => {
            if (!onPointClick) return
            const rect = e.currentTarget.getBoundingClientRect()
            const scaleX = viewport.width / rect.width
            const scaleY = viewport.height / rect.height
            const viewportX = (e.clientX - rect.left) * scaleX
            const viewportY = (e.clientY - rect.top) * scaleY
            const pdfViewport = page.getViewport({ scale: 1.5 })
            onPointClick(pdfViewport.convertToPdfPoint(viewportX, viewportY) as [number, number])
          }}
        >
          {measurements.filter(hasBbox).map((m) => {
            const pdfViewport = page.getViewport({ scale: 1.5 })
            const [x1, y1] = pdfViewport.convertToViewportPoint(m.bbox_min_x, m.bbox_min_y)
            const [x2, y2] = pdfViewport.convertToViewportPoint(m.bbox_max_x, m.bbox_max_y)
            const color = confidenceColor(m.confidence)
            const selected = m.id === selectedMeasurementId
            return (
              <rect
                key={m.id}
                x={Math.min(x1, x2)}
                y={Math.min(y1, y2)}
                width={Math.abs(x2 - x1)}
                height={Math.abs(y2 - y1)}
                stroke={color}
                fill={color}
                fillOpacity={selected ? 0.35 : 0.15}
                strokeWidth={selected ? 3 : 1.5}
                onClick={() => onSelectMeasurement(m.id)}
                className="cursor-pointer"
              />
            )
          })}
        </svg>
      )}
    </div>
  )
}
