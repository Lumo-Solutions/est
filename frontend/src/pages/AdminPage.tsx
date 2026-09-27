import { useState } from 'react'
import { ApprovalPoliciesAdmin } from '../features/admin/ApprovalPoliciesAdmin'
import { LayerTradeMappingAdmin } from '../features/admin/LayerTradeMappingAdmin'
import { ReasonCodesAdmin } from '../features/admin/ReasonCodesAdmin'
import { TaxonomyAdmin } from '../features/admin/TaxonomyAdmin'
import { TolerancesAdmin } from '../features/admin/TolerancesAdmin'
import { VendorRegionsAdmin } from '../features/admin/VendorRegionsAdmin'

const TABS = [
  { key: 'taxonomy', label: 'Taxonomy', Component: TaxonomyAdmin },
  { key: 'policies', label: 'Approval policies', Component: ApprovalPoliciesAdmin },
  { key: 'tolerances', label: 'Tolerances', Component: TolerancesAdmin },
  { key: 'layer-mapping', label: 'Layer/trade mapping', Component: LayerTradeMappingAdmin },
  { key: 'reason-codes', label: 'Reason codes', Component: ReasonCodesAdmin },
  { key: 'vendor-regions', label: 'Vendor regions', Component: VendorRegionsAdmin },
] as const

export function AdminPage() {
  const [activeTab, setActiveTab] = useState<(typeof TABS)[number]['key']>('taxonomy')
  const Active = TABS.find((t) => t.key === activeTab)?.Component ?? TaxonomyAdmin

  return (
    <div className="p-6">
      <h1 className="text-xl font-semibold text-slate-800">Admin</h1>
      <nav className="mt-3 flex gap-1 border-b border-slate-200">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setActiveTab(tab.key)}
            className={`rounded-t px-3 py-1.5 text-sm ${
              tab.key === activeTab ? 'border-b-2 border-slate-800 font-medium text-slate-800' : 'text-slate-500 hover:text-slate-700'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </nav>
      <div className="mt-4">
        <Active />
      </div>
    </div>
  )
}
