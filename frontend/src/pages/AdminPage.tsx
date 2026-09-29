import { useState } from 'react'
import { ApprovalPoliciesAdmin } from '../features/admin/ApprovalPoliciesAdmin'
import { LayerTradeMappingAdmin } from '../features/admin/LayerTradeMappingAdmin'
import { ReasonCodesAdmin } from '../features/admin/ReasonCodesAdmin'
import { TaxonomyAdmin } from '../features/admin/TaxonomyAdmin'
import { TolerancesAdmin } from '../features/admin/TolerancesAdmin'
import { VendorRegionsAdmin } from '../features/admin/VendorRegionsAdmin'
import { PageTitle } from '../components/PageTitle'
import { TabBar } from '../components/TabBar'

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
    <div className="px-6 py-6 xl:px-10">
      <PageTitle>Admin</PageTitle>
      {/* docs/ui-design-system.md section 4.5 / Figma Setting-page tabs. Kept as
          buttons (pattern="buttons") because admin-audit-permissions.spec.ts
          locates them with getByRole('button', { name }). */}
      <div className="mt-2">
        <TabBar
          pattern="buttons"
          label="Admin sections"
          idPrefix="admin"
          value={activeTab}
          onChange={(id) => setActiveTab(id as (typeof TABS)[number]['key'])}
          tabs={TABS.map((t) => ({ id: t.key, label: t.label }))}
        />
      </div>
      <div className="mt-6 rounded-card bg-white p-6">
        <Active />
      </div>
    </div>
  )
}
