import { useState } from 'react'
import { useAuth } from '../../auth/AuthContext'
import { Role } from '../../lib/roles'
import { useAdminReasonCodes, useCreateReasonCode, useUpdateReasonCode } from './api'

// Mirrors backend/app/api/v1/routes/settlement.py's _HEADER_ROLES.
const WRITE_ROLES = [Role.LEAD_ESTIMATOR, Role.PROCUREMENT_HEAD, Role.BD_DIRECTOR, Role.MANAGING_DIRECTOR]

export function ReasonCodesAdmin() {
  const { hasRole } = useAuth()
  const canWrite = hasRole(...WRITE_ROLES)
  const { data: codes } = useAdminReasonCodes()
  const createCode = useCreateReasonCode()
  const updateCode = useUpdateReasonCode()
  const [code, setCode] = useState('')
  const [label, setLabel] = useState('')

  return (
    <div>
      <h2 className="text-sm font-semibold text-slate-800">Win/loss reason codes</h2>
      {canWrite ? (
        <form
          className="mt-2 flex items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            createCode.mutate({ code, label }, { onSuccess: () => { setCode(''); setLabel('') } })
          }}
        >
          <input
            aria-label="Code"
            placeholder="Code"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            required
            className="rounded border border-slate-300 px-2 py-1.5 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
          />
          <input
            aria-label="Label"
            placeholder="Label"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            required
            className="rounded border border-slate-300 px-2 py-1.5 text-sm focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand"
          />
          <button
            type="submit"
            className="rounded bg-brand px-3 py-1.5 text-sm font-medium text-white transition-colors duration-150 hover:bg-brand-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-1"
          >
            Add
          </button>
        </form>
      ) : (
        <p className="mt-2 text-xs text-slate-500">Your role can view reason codes but not add or change them.</p>
      )}
      {createCode.isError && (
        <p role="alert" className="mt-1 text-sm text-danger">
          {createCode.error.message}
        </p>
      )}
      {updateCode.isError && (
        <p role="alert" className="mt-1 text-sm text-danger">
          {updateCode.error.message}
        </p>
      )}

      <table className="mt-4 w-full text-left text-sm">
        <thead className="border-b border-slate-200 font-medium text-slate-500">
          <tr><th className="py-2">Code</th><th>Label</th><th>Active</th></tr>
        </thead>
        <tbody>
          {(codes ?? []).map((c) => (
            <tr key={c.id} className="border-b border-slate-100 hover:bg-slate-50">
              <td className="py-2">{c.code}</td>
              <td>{c.label}</td>
              <td>
                <input
                  type="checkbox"
                  aria-label={`${c.label} active`}
                  checked={c.is_active}
                  disabled={!canWrite}
                  onChange={(e) => updateCode.mutate({ id: c.id, data: { is_active: e.target.checked } })}
                  className="accent-brand"
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
