import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { AppShell } from './app/AppShell'
import { AuthProvider } from './auth/AuthContext'
import { RequireAuth } from './auth/RequireAuth'
import { BoqImportWizardPage } from './pages/BoqImportWizardPage'
import { BoqReconciliationPage } from './pages/BoqReconciliationPage'
import { PlaceholderPage } from './pages/PlaceholderPage'
import { ProjectDetailPage } from './pages/ProjectDetailPage'
import { ProjectsListPage } from './pages/ProjectsListPage'
import { SheetIndexPage } from './pages/SheetIndexPage'
import { TakeoffViewerPage } from './pages/TakeoffViewerPage'
import { TypologyPage } from './pages/TypologyPage'

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
        <Route
          path="/projects/:projectId/procurement/packages"
          element={<PlaceholderPage title="Packages and RFQs" phase="8d" />}
        />
        <Route
          path="/projects/:projectId/procurement/quarantine"
          element={<PlaceholderPage title="Quarantine and review queue" phase="8d" />}
        />
        <Route
          path="/projects/:projectId/procurement/quotes"
          element={<PlaceholderPage title="Quote review and acceptance" phase="8d" />}
        />
        <Route
          path="/projects/:projectId/procurement/bid-leveling"
          element={<PlaceholderPage title="Bid-leveling matrix" phase="8d" />}
        />
        <Route
          path="/projects/:projectId/settlement"
          element={<PlaceholderPage title="Settlement cockpit" phase="8e" />}
        />
        <Route path="/projects/:projectId/export" element={<PlaceholderPage title="Export" phase="8e" />} />
        <Route
          path="/projects/:projectId/win-loss"
          element={<PlaceholderPage title="Win / loss capture" phase="8e" />}
        />
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
