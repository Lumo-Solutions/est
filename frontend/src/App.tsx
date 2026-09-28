import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { AppShell } from './app/AppShell'
import { AuthProvider } from './auth/AuthContext'
import { RequireAuth } from './auth/RequireAuth'
import { ApiError } from './lib/api'
import { AdminPage } from './pages/AdminPage'
import { AuditPage } from './pages/AuditPage'
import { BidLevelingPage } from './pages/BidLevelingPage'
import { BoqImportWizardPage } from './pages/BoqImportWizardPage'
import { BoqReconciliationPage } from './pages/BoqReconciliationPage'
import { ExportPage } from './pages/ExportPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { ProcurementPackagesPage } from './pages/ProcurementPackagesPage'
import { ProjectDetailPage } from './pages/ProjectDetailPage'
import { ProjectsListPage } from './pages/ProjectsListPage'
import { QuarantineQueuePage } from './pages/QuarantineQueuePage'
import { QuoteReviewPage } from './pages/QuoteReviewPage'
import { SettlementPage } from './pages/SettlementPage'
import { SheetIndexPage } from './pages/SheetIndexPage'
import { TakeoffViewerPage } from './pages/TakeoffViewerPage'
import { TypologyPage } from './pages/TypologyPage'
import { VendorDetailPage } from './pages/VendorDetailPage'
import { VendorDuplicatesPage } from './pages/VendorDuplicatesPage'
import { VendorsPage } from './pages/VendorsPage'
import { WinLossPage } from './pages/WinLossPage'

// A 4xx (not found, forbidden, validation) is never transient -- retrying it
// just delays a page's error state behind react-query's default 3-retry
// backoff (~7s) while every isLoading-gated page keeps showing "Loading...",
// indistinguishable from actually still loading. Only retry what a retry can
// plausibly fix: network failures and 5xx.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (failureCount, error) => {
        if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false
        return failureCount < 3
      },
    },
  },
})

// One placeholder route per screen listed in
// docs/preconstruction-build-brief.md's Phase 8, wired up for real as each
// sub-phase (8b-8f) lands.
function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<ProjectsListPage />} />
        <Route path="/vendors" element={<VendorsPage />} />
        <Route path="/vendors/duplicates" element={<VendorDuplicatesPage />} />
        <Route path="/vendors/:vendorId" element={<VendorDetailPage />} />
        <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
        <Route path="/projects/:projectId/drawings/:drawingId" element={<SheetIndexPage />} />
        <Route
          path="/projects/:projectId/drawings/:drawingId/sheets/:sheetIndex"
          element={<TakeoffViewerPage />}
        />
        <Route path="/projects/:projectId/typology" element={<TypologyPage />} />
        <Route path="/projects/:projectId/boq/import" element={<BoqImportWizardPage />} />
        <Route path="/projects/:projectId/boq" element={<BoqReconciliationPage />} />
        <Route path="/projects/:projectId/procurement/packages" element={<ProcurementPackagesPage />} />
        <Route path="/projects/:projectId/procurement/quarantine" element={<QuarantineQueuePage />} />
        <Route path="/projects/:projectId/procurement/quotes" element={<QuoteReviewPage />} />
        <Route path="/projects/:projectId/procurement/bid-leveling" element={<BidLevelingPage />} />
        <Route path="/projects/:projectId/settlement" element={<SettlementPage />} />
        <Route path="/projects/:projectId/export" element={<ExportPage />} />
        <Route path="/projects/:projectId/win-loss" element={<WinLossPage />} />
        <Route path="/admin" element={<AdminPage />} />
        <Route path="/audit" element={<AuditPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <RequireAuth>
            <AppRoutes />
          </RequireAuth>
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  )
}

export default App
