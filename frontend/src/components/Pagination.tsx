import { ChevronLeft, ChevronRight } from 'lucide-react'

// Figma Transaction-frame pager: Previous, numbered pages, Next; the active
// page is a solid brand pill. Presentational only -- the caller owns paging
// state (ProjectsListPage already pages server-side).
export function Pagination({
  page,
  pageCount,
  onPageChange,
}: {
  page: number
  pageCount: number
  onPageChange: (page: number) => void
}) {
  if (pageCount <= 1) return null
  const pages = Array.from({ length: pageCount }, (_, i) => i + 1)
  const ring = 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2'
  return (
    <nav aria-label="Pagination" className="flex items-center justify-end gap-2 text-base">
      <button
        type="button"
        disabled={page <= 1}
        onClick={() => onPageChange(page - 1)}
        className={`inline-flex items-center gap-1 rounded-control px-2 py-1 text-brand disabled:cursor-not-allowed disabled:opacity-50 ${ring}`}
      >
        <ChevronLeft aria-hidden="true" className="h-4 w-4" />
        Previous
      </button>
      {pages.map((p) => (
        <button
          key={p}
          type="button"
          aria-label={`Page ${p}`}
          aria-current={p === page ? 'page' : undefined}
          onClick={() => onPageChange(p)}
          className={`h-10 min-w-10 rounded-control px-3 tabular-nums ${ring} ${
            p === page ? 'bg-brand text-white' : 'text-brand hover:bg-brand-subtle'
          }`}
        >
          {p}
        </button>
      ))}
      <button
        type="button"
        disabled={page >= pageCount}
        onClick={() => onPageChange(page + 1)}
        className={`inline-flex items-center gap-1 rounded-control px-2 py-1 text-brand disabled:cursor-not-allowed disabled:opacity-50 ${ring}`}
      >
        Next
        <ChevronRight aria-hidden="true" className="h-4 w-4" />
      </button>
    </nav>
  )
}
