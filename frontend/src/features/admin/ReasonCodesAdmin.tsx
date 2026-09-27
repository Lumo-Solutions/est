import { useState } from 'react'
import { useAdminReasonCodes, useCreateReasonCode, useUpdateReasonCode } from './api'

export function ReasonCodesAdmin() {
  const { data: codes } = useAdminReasonCodes()
  const createCode = useCreateReasonCode()
  const updateCode = useUpdateReasonCode()
  const [code, setCode] = useState('')
  const [label, setLabel] = useState('')

  return (
    <div>
      <h2 className="text-sm font-semibold text-slate-800">Win/loss reason codes</h2>
      <form
        className="mt-2 flex items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          createCode.mutate({ code, label }, { onSuccess: () => { setCode(''); setLabel('') } })
        }}
      >
        <input placeholder="Code" value={code} onChange={(e) => setCode(e.target.value)} required className="rounded border border-slate-300 px-2 py-1 text-sm" />
        <input placeholder="Label" value={label} onChange={(e) => setLabel(e.target.value)} required className="rounded border border-slate-300 px-2 py-1 text-sm" />
        <button type="submit" className="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white">
          Add
        </button>
      </form>
      {createCode.isError && <p className="mt-1 text-sm text-red-600">{createCode.error.message}</p>}

      <table className="mt-4 w-full text-left text-sm">
        <thead className="border-b border-slate-200 text-slate-500">
          <tr><th>Code</th><th>Label</th><th>Active</th></tr>
        </thead>
        <tbody>
          {(codes ?? []).map((c) => (
            <tr key={c.id} className="border-b border-slate-100">
              <td>{c.code}</td>
              <td>{c.label}</td>
              <td>
                <input
                  type="checkbox"
                  checked={c.is_active}
                  onChange={(e) => updateCode.mutate({ id: c.id, data: { is_active: e.target.checked } })}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
