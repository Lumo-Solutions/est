import { Link, useParams } from 'react-router-dom'
import { useDrawing, useSheets } from '../features/drawings/api'

export function SheetIndexPage() {
  const { projectId, drawingId } = useParams()
  const { data: drawing } = useDrawing(drawingId)
  const { data: sheets, isLoading, isError, error } = useSheets(drawingId)

  return (
    <div className="p-6">
      <h1 className="text-xl font-semibold text-slate-800">{drawing?.original_filename ?? 'Sheets'}</h1>
      {drawing && <p className="mt-1 text-sm text-slate-500">Status: {drawing.status}</p>}
      {isLoading && <p className="mt-4 text-slate-500">Loading...</p>}
      {isError && <p className="mt-4 text-red-600">{error.message}</p>}
      {sheets && sheets.length === 0 && (
        <p className="mt-4 text-sm text-slate-500">
          No sheets indexed yet -- extraction may still be running.
        </p>
      )}
      {sheets && sheets.length > 0 && (
        <table className="mt-4 w-full text-left text-sm">
          <thead className="border-b border-slate-200 text-slate-500">
            <tr>
              <th className="py-2">#</th>
              <th>Drawing no.</th>
              <th>Title</th>
              <th>Revision</th>
              <th>Discipline</th>
              <th>Scale</th>
              <th>Extraction</th>
            </tr>
          </thead>
          <tbody>
            {sheets.map((s) => (
              <tr key={s.id} className="border-b border-slate-100 hover:bg-slate-50">
                <td className="py-2">
                  <Link
                    to={`/projects/${projectId}/drawings/${drawingId}/sheets/${s.sheet_index}`}
                    className="text-slate-800 hover:underline"
                  >
                    {s.sheet_index + 1}
                  </Link>
                </td>
                <td>{s.drawing_number ?? '--'}</td>
                <td>{s.sheet_title ?? s.source_name ?? '--'}</td>
                <td>{s.revision ?? '--'}</td>
                <td>{s.discipline ?? '--'}</td>
                <td>
                  {s.scale_text ?? (s.scale_ratio ? `1:${Math.round(1 / s.scale_ratio)}` : '--')}
                  {s.scale_disagreement && (
                    <span className="ml-1 text-amber-600" title="Scale sources disagree">
                      ⚠
                    </span>
                  )}
                </td>
                <td>{s.extraction_status ?? '--'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
