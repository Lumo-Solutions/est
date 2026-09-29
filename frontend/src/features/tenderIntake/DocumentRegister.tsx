import { useState } from 'react'
import { Badge } from '../../components/Badge'
import { Card, SectionHeading } from '../../components/Card'
import { controlClasses } from '../../components/Field'
import { Pagination } from '../../components/Pagination'
import { SkeletonRows } from '../../components/Skeleton'
import { Table, TableCard, Td, Th } from '../../components/Table'
import { useDocumentRegister, useTenderClasses, useTenderPackages } from './api'
import { isSuperseded } from './lib'
import { useDebounced } from './useDebounced'

const PAGE_SIZE = 50

export function DocumentRegister({ projectId }: { projectId: string }) {
  const [docClass, setDocClass] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const q = useDebounced(search, 300)
  const { data: classes = [] } = useTenderClasses()
  const { data: packages = [] } = useTenderPackages(projectId)
  const { data, isLoading, isError, error } = useDocumentRegister(projectId, {
    doc_class: docClass || undefined,
    q: q || undefined,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  })
  const label = (code: string | null) => (code ? (classes.find((c) => c.code === code)?.label ?? code) : '--')
  const pageCount = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1

  return (
    <Card className="mt-6">
      <SectionHeading>Project document register</SectionHeading>
      <div className="mb-3 flex flex-wrap items-end gap-4">
        <div>
          <label htmlFor="register-class" className="mb-1 block text-sm text-ink">
            Register class
          </label>
          <select
            id="register-class"
            value={docClass}
            onChange={(e) => {
              setDocClass(e.target.value)
              setPage(1)
            }}
            className={controlClasses}
          >
            <option value="">All classes</option>
            {classes.map((c) => (
              <option key={c.code} value={c.code}>
                {c.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="register-search" className="mb-1 block text-sm text-ink">
            Search register
          </label>
          <input
            id="register-search"
            type="search"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value)
              setPage(1)
            }}
            className={controlClasses}
          />
        </div>
      </div>
      {isLoading && <SkeletonRows count={3} />}
      {isError && (
        <p role="alert" className="text-sm text-danger">
          {error.message}
        </p>
      )}
      {data && data.items.length === 0 && <p className="text-base text-ink-2">No documents are in the register yet.</p>}
      {data && data.items.length > 0 && (
        <>
          <TableCard>
            <Table aria-label="Project document register">
              <thead>
                <tr>
                  <Th>Class</Th>
                  <Th>Number</Th>
                  <Th>Title</Th>
                  <Th>Revision</Th>
                  <Th>File</Th>
                  <Th>Received</Th>
                  <Th>Download</Th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((d) => {
                  const name = d.archive_path ?? d.original_filename
                  return (
                    <tr key={d.id}>
                      <Td>{label(d.doc_class)}</Td>
                      <Td>{d.document_number ?? '--'}</Td>
                      <Td>{d.title ?? '--'}</Td>
                      <Td>
                        {d.revision_label ?? '--'} {isSuperseded(d, data.items) && <Badge tone="neutral">Superseded</Badge>}
                      </Td>
                      <Td>{name}</Td>
                      <Td>{packages.find((p) => p.id === d.package_id)?.received_date ?? d.created_at.slice(0, 10)}</Td>
                      <Td>
                        <a
                          href={`/api/v1/tender-documents/${d.id}/download`}
                          aria-label={`Download ${name}`}
                          className="rounded text-brand hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
                        >
                          Download
                        </a>
                      </Td>
                    </tr>
                  )
                })}
              </tbody>
            </Table>
          </TableCard>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-sm text-ink-2">
            <span>
              Showing {data.offset + 1} to {data.offset + data.items.length} of {data.total}
            </span>
            <Pagination page={page} pageCount={pageCount} onPageChange={setPage} />
          </div>
        </>
      )}
    </Card>
  )
}
