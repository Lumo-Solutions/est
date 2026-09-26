import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { AppShell } from './app/AppShell'
import { AuthProvider } from './auth/AuthContext'
import { RequireAuth } from './auth/RequireAuth'
import { BidLevelingPage } from './pages/BidLevelingPage'
import { BoqImportWizardPage } from './pages/BoqImportWizardPage'
import { BoqReconciliationPage } from './pages/BoqReconciliationPage'
import { ExportPage } from './pages/ExportPage'
import { PlaceholderPage } from './pages/PlaceholderPage'
import { ProcurementPackagesPage } from './pages/ProcurementPackagesPage'
import { ProjectDetailPage } from './pages/ProjectDetailPage'
import { ProjectsListPage } from './pages/ProjectsListPage'
import { QuarantineQueuePage } from './pages/QuarantineQueuePage'
import { QuoteReviewPage } from './pages/QuoteReviewPage'
import { SettlementPage } from './pages/SettlementPage'
import { SheetIndexPage } from './pages/SheetIndexPage'
import { TakeoffViewerPage } from './pages/TakeoffViewerPage'
import { TypologyPage } from './pages/TypologyPage'
import { WinLossPage } from './pages/WinLossPage'

const queryClient = new QueryClient()

// One placeholder route per screen listed in
// docs/preconstruction-build-brief.md's Phase 8, wired up for real as each
// sub-phase (8b-8f) lands.
function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<ProjectsListPage />} />
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
        <Route path="/admin" element={<PlaceholderPage title="Admin" phase="8f" />} />
        <Route path="/audit" element={<PlaceholderPage title="Audit viewer" phase="8f" />} />
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
