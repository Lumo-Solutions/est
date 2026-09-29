import { Link } from 'react-router-dom'
import { Card, SectionHeading } from '../../components/Card'
import { SkeletonRows } from '../../components/Skeleton'
import { Table, TableCard, Td, Th } from '../../components/Table'
import { useProjectAddenda } from './api'

export function AddendaRegister({ projectId }: { projectId: string }) {
  const { data, isLoading, isError, error } = useProjectAddenda(projectId)
  return (
    <Card className="mt-6">
      <SectionHeading>Addenda register</SectionHeading>
      {isLoading && <SkeletonRows count={2} />}
      {isError && (
        <p role="alert" className="text-sm text-danger">
          {error.message}
        </p>
      )}
      {data && data.length === 0 && <p className="text-base text-ink-2">No addenda have been routed for this project yet.</p>}
      {data && data.length > 0 && (
        <TableCard>
          <Table aria-label="Addenda register">
            <thead>
              <tr>
                <Th>No.</Th>
                <Th>Issue date</Th>
                <Th>Title</Th>
                <Th>What it changes</Th>
                <Th>Settlements to re-check</Th>
              </tr>
            </thead>
            <tbody>
              {data.map((a) => (
                <tr key={a.id}>
                  <Td>{a.addendum_no ?? '--'}</Td>
                  <Td>{a.issue_date ?? '--'}</Td>
                  <Td>{a.title ?? '--'}</Td>
                  <Td>
                    {a.links.length === 0 && <span className="text-ink-2">--</span>}
                    <ul className="space-y-0.5">
                      {a.links.map((l) => (
                        <li key={l.id}>
                          {l.action} {l.reference_text}{' '}
                          <span className="text-ink-2">({l.resolved ? 'linked' : 'not found yet'})</span>
                        </li>
                      ))}
                    </ul>
                  </Td>
                  <Td numeric={false}>
                    <span className="tabular-nums">{a.open_settlement_ids.length}</span>
                    {a.open_settlement_ids.length > 0 && (
                      <>
                        {' '}
                        <Link
                          to={`/projects/${projectId}/settlement`}
                          aria-label={`Open settlement for addendum ${a.addendum_no ?? ''}`.trim()}
                          className="rounded text-brand hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
                        >
                          Open settlement
                        </Link>
                      </>
                    )}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </TableCard>
      )}
    </Card>
  )
}
