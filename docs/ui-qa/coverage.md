# UI QA coverage matrix — page x role x action

Built from a full walk of `frontend/src` (routes in `frontend/src/App.tsx`,
nav gating in `frontend/src/app/AppShell.tsx`) and every route file under
`backend/app/api/v1/routes/`. Role-gating shown here is what the **UI**
does (nav visibility, a page's own conditional rendering) — it is a UX
nicety only. The server (`require_roles`/service-layer checks) is the real
enforcement in every case; Phase 2 verifies both agree, and never treats a
UI hide as proof the server is also protected.

Roles: `estimator` (est), `lead_estimator` (lead), `procurement_head`
(proc), `bd_director` (bd), `managing_director` (md), `platform_admin`
(admin, Keycloak-only role not in the SRS's five — controls the
quarantine queue's tenant-resolution action).

## 1. Routed pages

| Route | Component | UI nav gate | Key actions | Endpoint(s) |
|---|---|---|---|---|
| `/` | `ProjectsListPage.tsx` | all authenticated (global nav, always visible) | New project (create) | `GET /projects`, `POST /projects` (server: bd/md) |
| `/projects/:id` | `ProjectDetailPage.tsx` | all | Upload drawing, ingest/extract | `GET /projects/{id}`, `GET/POST /projects/{id}/drawings`, `POST /drawings/{id}/ingest` — **no edit-location or add-member UI** (see gaps) |
| `/projects/:id/drawings/:did` | `SheetIndexPage.tsx` | all | (read-only) sheet list | `GET /drawings/{id}`, `GET /drawings/{id}/sheets` |
| `/projects/:id/drawings/:did/sheets/:idx` | `TakeoffViewerPage.tsx` | all | Calibrate scale, revert calibration, override/revert measurement, link region | `PATCH .../scale`, `POST .../scale-calibrations/{id}/revert`, `POST /drawing-measurements/{id}/override(/revert)`, `GET /drawing-sheets/{id}/entities` |
| `/projects/:id/typology` | `TypologyPage.tsx` | all | Detect clusters, confirm/reject cluster, edit variant deltas | `POST .../typology-clusters/detect`, `POST .../confirm`, `POST .../reject`, `GET .../deltas` |
| `/projects/:id/boq/import` | `BoqImportWizardPage.tsx` | all | Upload file, map columns, preview, commit | `POST .../boq-items:import-preview`, `POST .../boq-items:import-commit` |
| `/projects/:id/boq` | `BoqReconciliationPage.tsx` | all | Reconcile, link/unlink measurement, accept/reject suggestion | `POST /boq-items/{id}/reconcile`, `POST/DELETE .../measurements(/{id})`, `POST /semantic-matching/feedback` — **no delete-BOQ-item UI** (server has `DELETE /boq-items/{id}`, lead/proc/md) |
| `/projects/:id/procurement/packages` | `ProcurementPackagesPage.tsx` | **est, lead, proc** (nav-gated) | Create package, add items, match vendors, draft RFQs, dispatch, resend (`window.prompt` for reason) | `POST .../procurement-packages`, `POST .../items`, `GET .../matched-vendors`, `POST .../rfqs`, `POST /rfqs/{id}/dispatch` (step-up), `POST /rfqs/{id}/resend` |
| `/projects/:id/procurement/quarantine` | `QuarantineQueuePage.tsx` | all (page); "Resolve tenant" admin-only in-page | Resolve-tenant (`window.prompt`), attach, dismiss (`window.prompt`) | `POST .../resolve-tenant` (server: `platform_admin`), `.../attach` (proc/bd/md), `.../dismiss` |
| `/projects/:id/procurement/quotes` | `QuoteReviewPage.tsx` | all | Set currency/VAT, accept/reject line, reject quotation, promote version | `POST .../resolve-currency-vat`, `.../accept`, `.../reject`, `.../promote` — **no attachments viewer, no exclusion-flags acknowledge UI, no fx-rate UI** (endpoints exist) |
| `/projects/:id/procurement/bid-leveling` | `BidLevelingPage.tsx` | all | Select package/vendor cell | `GET .../bid-leveling`, `.../quotation-totals`, `GET /quotations/{id}/exclusion-flags` (display only, no acknowledge action) |
| `/projects/:id/settlement` | `SettlementPage.tsx` | **lead, bd, md** (nav-gated); submit is server bd/md; Approve/Reject disabled client-side for the submitter (SoD) | Build draft, 4 default-% sliders, save/reload scenario, submit, approve/reject (MFA step-up) | `POST .../bid-settlements`, `.../simulate`, `.../scenarios`, `.../submit`, `.../decide` — **no per-trade/per-line override UI** (server has `PUT .../trade-overrides/{id}`, `PATCH .../lines/{id}`), **no delete-scenario UI** (no server endpoint either — known gap) |
| `/projects/:id/export` | `ExportPage.tsx` | all | VAT toggle, download generated, preview + download original | `POST .../export`, `.../export-original/preview`, `.../export-original` |
| `/projects/:id/win-loss` | `WinLossPage.tsx` | all (server: record-outcome is bd/md) | Record outcome (won/lost, prices, reason codes, note) | `GET /settlement-reason-codes`, `POST .../outcome` |
| `/admin` | `AdminPage.tsx` | **admin, md** | Tabs: Taxonomy, Approval policies, BOQ tolerances, Layer-trade mapping, Reason codes, **Vendor service-regions** (the *only* vendor-touching UI in the app) | see sub-tabs below |
| `/audit` | `AuditPage.tsx` | **admin, md, bd** | Filter by entity; verify hash chain (**md**-only in-page) | `GET /audit/events`, `GET /audit/verify` |

**Admin tab endpoints:** Taxonomy `GET/POST/PATCH /taxonomy`, `.../move`; Approval policies `GET/POST /approvals/policies`, `PATCH .../{id}` (server: **md-only writes**); BOQ tolerances `GET/PUT /projects/{id}/boq-tolerances`; Layer-trade mapping `GET/PUT /projects/{id}/drawing-layer-trade-mappings`; Reason codes `GET/POST/PATCH /settlement-reason-codes`; Vendor regions `GET /vendors`, `GET/PUT /vendors/{id}/service-regions`.

**No 404 / catch-all route**: `App.tsx`'s `<Routes>` has no `path="*"` — a bad or missing id currently falls through to whatever page tries to render with an undefined id, not a 404. An unused `PlaceholderPage.tsx` already exists in the repo (built for Phase 8's screen-by-screen rollout, never wired to a catch-all) — logging as a P1 candidate for Phase 2, likely fixable by wiring it as the `*` route.

**No `/login` or `/callback` route registered** — by design: `RequireAuth` redirects an unauthenticated user straight to the backend's `GET /api/v1/auth/login`, which redirects to Keycloak; there is no SPA-side login screen to route to (`LoginPage.tsx` exists but appears unused by the router — verify in Phase 2 whether it's dead code or reachable some other way).

## 2. Backend capabilities with NO frontend page at all

Per the brief's Phase 1 candidate list, confirmed by grepping `frontend/src`
for any reference to each resource:

| Capability | Backend endpoints (exist, unused by any page) | Server roles |
|---|---|---|
| **Vendor master, create, search, duplicate review** | `GET/POST /vendors`, `POST /vendors:check-duplicates`, `GET /vendors/duplicates/list`, `POST /vendors/duplicates/{id}/resolve`, `POST /vendors/{id}/duplicate-scan`, `GET /vendors/{id}` | read: any; write: lead/proc/bd/md |
| **Prequalification & certificates (+ expiry)** | `GET /authorities`, `GET /certificate-types`, `POST /vendor-certificates`, `POST /vendor-certificates/{id}/verify`, `GET/POST /vendors/{id}/prequalification` | read: any; write: proc/lead/md |
| **Cost library (as-of + rate history)** | `POST /cost-items`, `GET /cost-items/{id}`, `POST /cost-items/{id}/rates`, `GET /cost-items/{id}/rate` (as-of date) | read: any; write: lead/proc/md |
| **Users & roles (read-only, Keycloak-sourced)** | **No backend endpoint exists at all** — not just missing UI. Needs a new read-only endpoint (Phase 3) that calls Keycloak's admin API server-side; no `/users` resource anywhere in `backend/app/api/v1/routes/`. |
| **Module E (post-award, read views)** | `GET /projects/{id}/contracts`, `/contracts/{id}`, `/contracts/{id}/revisions`, `/contracts/{id}/variations`, `/projects/{id}/boq-revisions`, `/projects/{id}/exclusion-register`, `/projects/{id}/outturn-cost-observations` | read: any |

Partial gaps (endpoint exists, page exists, but the specific action doesn't):
- **Project editing/members**: `PATCH /projects/{id}/location` (bd/md) and `POST /projects/{id}/members` (bd/md/lead) have no UI on `ProjectDetailPage`.
- **Saved-scenario delete**: no UI *and* no backend endpoint (Phase 3 explicitly adds the endpoint).
- **Quotation attachments viewer**: `GET /quotations/{id}/attachments` unused.
- **Exclusion-flag acknowledge**: `POST /quotation-exclusion-flags/{id}/acknowledge` unused (flags are shown read-only in bid-leveling, never acknowledged).
- **fx-rate overrides**: `PATCH /quotations/{id}/fx-rate`, `POST /bid-settlements/{id}/lines/{id}/fx-rate` unused.
- **Settlement per-trade/per-line overrides**: `PUT .../trade-overrides/{id}`, `PATCH .../lines/{id}` unused (only the 4 project-default sliders are exposed) — already a known Phase 3 item.
- **BOQ item delete**: `DELETE /boq-items/{id}` unused.

## 3. Known pre-existing UX debt already documented (build report), reconfirmed here
- `window.prompt`/`window.confirm` used in `QuarantineQueuePage` (resolve-tenant, attach, dismiss) and `ProcurementPackagesPage` (resend reason) — Phase 3 replaces with modals.
- Taxonomy editor is a plain parent-id form, not a tree UI — Phase 3.
- No home dashboard per role — Phase 3.

## 4. Cross-cutting items for Phase 2 to verify per role (not yet walked live)
- Whether every "all authenticated" UI page correctly still 403s server-side for a role that shouldn't be able to *write* on it (e.g. an `estimator` hitting `POST /vendors` directly) — the matrix above records the server role from the route decorator, but Phase 2 must confirm live, not just by reading code.
- Whether nav-hidden pages (e.g. `/projects/:id/settlement` for an `estimator`) still correctly 403 if navigated to directly by URL — nothing in `App.tsx`'s routes wraps individual routes in a role guard beyond the blanket `RequireAuth` (authentication only, not authorization), so page-level access currently relies entirely on each page's own data calls 403ing. Needs a live check per role in Phase 2.
