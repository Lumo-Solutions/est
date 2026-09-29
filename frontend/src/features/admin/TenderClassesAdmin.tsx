import { useState } from 'react'
import { useAuth } from '../../auth/AuthContext'
import { Button } from '../../components/Button'
import { Table, TableCard, Td, Th } from '../../components/Table'
import { Role } from '../../lib/roles'
import { useTenderClasses, useUpdateTenderClass } from '../tenderIntake/api'
import type { TenderClass } from '../tenderIntake/types'

// Mirrors backend/app/intake/constants.py::CLASS_ADMIN_ROLES (PATCH /tender-classes).
const ADMIN_ROLES = [Role.MANAGING_DIRECTOR]

function ClassRow({ item, canWrite }: { item: TenderClass; canWrite: boolean }) {
  const update = useUpdateTenderClass()
  const [label, setLabel] = useState(item.label)
  const dirty = label.trim() !== item.label && label.trim() !== ''
  return (
    <tr className="border-b border-row-rule">
      <Td>{item.code}</Td>
      <Td>
        <input
          aria-label={`Label for ${item.code}`}
          value={label}
          disabled={!canWrite}
          maxLength={128}
          onChange={(e) => setLabel(e.target.value)}
          className="w-full rounded-control border border-outline px-3 py-1.5 text-sm text-ink focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand disabled:bg-canvas"
        />
      </Td>
      <Td className="text-ink-2">{item.default_label}</Td>
      <Td>
        <input
          type="checkbox"
          aria-label={`Enable ${item.code}`}
          checked={item.enabled}
          disabled={!canWrite || update.isPending}
          onChange={(e) => update.mutate({ code: item.code, enabled: e.target.checked })}
        />
      </Td>
      <Td>
        {canWrite && (
          <div className="flex items-center gap-2">
            <Button size="sm" disabled={!dirty || update.isPending} aria-label={`Save label for ${item.code}`} onClick={() => update.mutate({ code: item.code, label: label.trim() })}>
              Save
            </Button>
            {label.trim() !== item.default_label && (
              <Button
                size="sm"
                variant="secondary"
                disabled={update.isPending}
                aria-label={`Reset label for ${item.code}`}
                onClick={() => {
                  setLabel(item.default_label)
                  update.mutate({ code: item.code, label: item.default_label })
                }}
              >
                Reset
              </Button>
            )}
          </div>
        )}
        {update.isError && (
          <p role="alert" className="mt-1 text-xs text-danger">
            {update.error.message}
          </p>
        )}
      </Td>
    </tr>
  )
}

export function TenderClassesAdmin() {
  const { hasRole } = useAuth()
  const canWrite = hasRole(...ADMIN_ROLES)
  const { data, isLoading, isError, error } = useTenderClasses()

  return (
    <div>
      <h2 className="text-lg font-semibold text-ink-title">Tender document classes</h2>
      <p className="mt-1 text-sm text-muted">
        The classes intake proposes for uploaded tender documents. Rename one to match your own wording, or disable one you never use: a
        disabled class cannot be confirmed, so those documents must be reclassified first.
        {!canWrite && ' Your role can view the classes but not change them.'}
      </p>
      {isLoading && <p className="mt-3 text-sm text-muted">Loading...</p>}
      {isError && (
        <p role="alert" className="mt-3 text-sm text-danger">
          {error.message}
        </p>
      )}
      {data && (
        <TableCard className="mt-3">
          <Table aria-label="Tender document classes">
            <thead>
              <tr>
                <Th>Code</Th>
                <Th>Label</Th>
                <Th>Default</Th>
                <Th>Enabled</Th>
                <Th>Actions</Th>
              </tr>
            </thead>
            <tbody>
              {data.map((c) => (
                <ClassRow key={`${c.code}-${c.label}-${c.enabled}`} item={c} canWrite={canWrite} />
              ))}
            </tbody>
          </Table>
        </TableCard>
      )}
    </div>
  )
}
