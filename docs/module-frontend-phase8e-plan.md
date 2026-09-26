# Phase 8e plan: settlement + export + win/loss

Per `docs/module-frontend-phase8-plan.md` §2's sub-phase breakdown.

## 0. What already exists (confirmed by reading the backend code)

Read `app/api/v1/routes/{settlement,approvals}.py` and their schemas in
full before writing this, and cross-checked every route against every
`async def` in `app/services/settlement.py` (the same audit method that
found real gaps in 8b/8d and none in 8c).

- **Live simulation**: `POST /bid-settlements/{id}/simulate` is entirely
  stateless (no DB writes) -- it takes optional default percentages plus
  per-trade/per-line override dicts and returns a full per-line breakdown
  **and `required_role`**. The server computes the sell_total/margin
  approval-tier routing itself and hands it straight to the client --
  the frontend never reimplements that threshold logic, it just displays
  whatever `required_role` comes back. Sliders call this endpoint on
  every change (debounced client-side); nothing is persisted until an
  explicit save.
- **Saved scenarios**: create + list exist (`POST`/`GET
  .../scenarios`); no delete. Not blocking -- the screen just has no
  delete button for a scenario.
- **Submit/approve/reject + SoD + MFA step-up**: `POST .../submit`
  creates the `ApprovalRequest`; `POST .../decide` is a thin wrapper over
  the generic `approvals_service.decide()` used everywhere else in this
  build. SoD is enforced there (`ForbiddenError` if the decider is the
  same user as `submitted_by`) -- the UI greys out the approve/reject
  controls client-side using the same comparison (`user.sub ===
  settlement.submitted_by`), purely a nicety, the server is the real
  gate. MFA step-up (`StepUpRequiredError` when `ctx.acr` is below
  "silver") fires specifically on `/decide`, not `/submit` -- Phase 8a's
  API client already intercepts this generically, nothing new needed
  here.
- **Export + fidelity report**: `POST .../export` (generated xlsx,
  `include_vat`/`vat_pct`) and the "original" path -- `POST
  .../export-original/preview` returns `FidelityReportOut` (`ok`,
  `lost_features[]`, `unexpected_cell_changes[]`) for review *before*
  `POST .../export-original` (gated on `accept_loss: true` once the
  reviewer has seen the preview). Both export endpoints return raw xlsx
  bytes (`Content-Disposition`/`X-File-SHA256` headers), not a JSON body
  with a download link -- the frontend needs a small raw-fetch helper
  (bypassing the typed JSON API client) to turn the response into a
  downloaded file.
- **Win/loss**: folded into the settlement itself, not a separate
  entity -- `POST .../outcome` (`OutcomeRequest`: `outcome`
  "won"/"lost", `our_price`, `winning_price`, `competitor_names[]`,
  `competitor_vendor_ids[]`, `reason_codes[]`, `note`), reason codes from
  `GET /settlement-reason-codes`.
- **One real, narrow gap found** (mirrors 8b/8d's pattern; 8c had
  none): **no endpoint listed a project's settlements** -- only
  `build_settlement_draft` (creates) and get-by-id (needs an
  already-known id) existed. Without it the settlement screen has no way
  to land on a project and discover whether a settlement already
  exists, or browse its version/win-loss history. **Fixed**:
  `app/services/settlement.py::list_settlements()` (mirrors every prior
  gap-fix's exact shape) + `GET /projects/{id}/bid-settlements`, reusing
  the existing `BidSettlementOut` schema (its `lines`/`trade_overrides`
  fields default to `[]`, so the list response stays lightweight --
  header fields only, no N+1 detail fetch per settlement). Integration-
  tested by extending the existing "rejected settlement allows a new
  version" test (it already creates two real versions of one project's
  settlement) with one more assertion, plus a new small non-member
  RLS-visibility test.

## 1. Screens

- **Settlement cockpit** (`/projects/:id/settlement`): on load, list a
  project's settlements (the new endpoint) -- if none exists, a "Build
  draft" button; if one does, open the current version. Live sliders
  (project defaults + per-trade + per-line overrides) call `/simulate`
  on every change (debounced), showing the full breakdown and the
  `required_role` badge live. Saved scenarios (save current slider state
  + its result; list and re-apply one). Submit (role-gated); approve/
  reject via `/decide` (SoD-greyed for the submitter, MFA step-up handled
  generically by the existing API client). A version history strip using
  the new list endpoint (`version_no`/`is_current`/`status`).
- **Export** (`/projects/:id/export`, its own route -- already scaffolded
  as a placeholder in Phase 8a's routing skeleton, kept as-is rather than
  folded into the cockpit): resolves the project's current settlement via
  the new list endpoint, then "Generated" (`/export`, VAT toggle)
  downloads directly; "Original" first calls `/export-original/preview`,
  shows the fidelity report (lost features / unexpected cell changes) for
  the reviewer to read, and only enables the real `/export-original`
  (with `accept_loss: true`) after that review.
- **Win/loss** (`/projects/:id/win-loss`, its own route, same reasoning):
  resolves the current settlement, then a form for `OutcomeRequest`
  (outcome, our price, winning price, competitor names/vendor ids,
  reason codes from `GET /settlement-reason-codes`, note); read-only once
  recorded (`record_outcome` is a single call -- the settlement's own
  `outcome_*` fields already show what was recorded, no separate read
  endpoint needed).

## 2. Explicitly out of scope for 8e

- Admin, audit -- 8f.
- Scenario delete -- no backend endpoint exists; not invented here (a
  schema-only gap-filling exercise the brief doesn't ask for).
