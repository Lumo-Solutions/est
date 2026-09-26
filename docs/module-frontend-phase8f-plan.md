# Phase 8f plan: admin + audit + closeout

Per `docs/module-frontend-phase8-plan.md` §2's sub-phase breakdown. This
is the final Phase 8 sub-phase.

## 0. What already exists (confirmed by reading the backend code)

Read `app/api/v1/routes/{taxonomy,vendors,approvals,settlement,audit}.py`
and their schemas/services in full before writing this, cross-checking
every route against every `async def` in the corresponding service files
(the same audit method that found real gaps in 8b/8d/8e; 8c had none).

- **Taxonomy** (trade tree): full CRUD already exposed --
  create/list/get/subtree/update/move (`app/api/v1/routes/taxonomy.py`).
  `TradeNodeOut` carries both `parent_id` and an ltree `path` string.
  No gap.
- **Vendor regions**: `GET`/`PUT /vendors/{id}/service-regions` (plain
  `list[str]` of emirate names, whole-set replace) already exposed --
  already known from Phase 6/8d's own vendor-geography work. No gap.
- **Tolerances** and **layer/trade mapping**: `GET`/`PUT
  /projects/{id}/boq-tolerances` and `GET`/`PUT
  /projects/{id}/drawing-layer-trade-mappings` already exposed --
  already known and typed from Phase 8b/8c. No gap, no screen built yet
  though (deferred to this phase, since they're admin-flavoured config).
- **Audit viewer**: `GET /audit/events` (`entity_type?`, `entity_id?`,
  `limit`<=500) + `GET /audit/verify` (`date_from`, `date_to`,
  `managing_director`-only hash-chain verification) already exposed,
  `_READ_ROLES` = lead_estimator/procurement_head/bd_director/
  managing_director (tighter than most reads -- no estimator). Fully
  sufficient for a read-only viewer. No gap.
- **Two real gaps found** (mirrors 8b/8d/8e's pattern):
  1. **Approval policies had zero API routes at all.**
     `ApprovalPolicy`/`ApprovalPolicyTier` are real, already-live-read DB
     tables (`app/services/approvals.py::_active_policy()`/
     `route_tiers()` already read them on every settlement submit/
     simulate), but only `app/cli.py`'s dev-seed ever wrote a row -- no
     admin could view or change them without a raw SQL console. The
     brief's own "admin: approval policies" screen needs this. **Fixed**:
     `GET`/`POST /approvals/policies` + `PATCH
     /approvals/policies/{id}` (activate/deactivate), reusing the
     tenant's own RLS write-role restriction on these two tables
     (`app/migrations/versions/0008_approvals.py`:
     `write_roles=["managing_director"]`) as the route-level gate too --
     this is a governance control (who has authority to approve what
     money), deliberately restricted to a single senior tier rather than
     the usual three-role "structure" set. Creating a new version never
     deactivates the prior one automatically (`_active_policy()` always
     picks the highest active version, so a stale active version is
     harmless, just never selected) -- `set_policy_active` exists for an
     admin who wants the old one visibly retired.
  2. **Settlement reason codes were read-only.** Only `GET
     /settlement-reason-codes` (active-only, for the win/loss form)
     existed; no create/update/deactivate for the admin managing the
     list itself. **Fixed**: the existing GET gained an
     `include_inactive` query param (default `false`, so the win/loss
     form's own behaviour is unchanged) plus new `POST`/`PATCH
     /settlement-reason-codes[/{id}]`, gated at the same `_HEADER_ROLES`
     tier as every other Module D1 config write in this file, matching
     the existing DB RLS write-role list on this table exactly
     (`app/migrations/versions/0020_boq_import_retention_winloss.py`:
     `REASON_CODE_WRITE_ROLES`).

## 1. Screens

- **Admin** (`/admin`, tabbed): taxonomy (tree view, create/move/
  rename/deactivate a node), approval policies (list by entity_type +
  version, a create form for a new version's tiers, activate/deactivate),
  tolerances (per-project -- picks a project first, then the existing
  tolerance list/set), layer-to-trade mapping (per-project, whole-set
  replace form, same pattern), reason codes (list incl. inactive,
  create, toggle active), vendor regions (per-vendor -- picks a vendor
  first, then the existing region list/replace).
- **Audit viewer** (`/audit`, read-only): a filterable event list
  (`entity_type`/`entity_id`/`limit`), each row showing actor/action/
  entity/timestamp/hash; a chain-verify panel (date range) visible only
  to `managing_director` (UI-gated to match the route's own role gate).

## 2. Final vitest/Playwright gap-filling

A pass over every sub-phase's own "known gaps" in `docs/build-log.md`
for anything that's actually a missing *test* rather than a missing
*feature* (the latter stays out of scope -- Phase 9 is for the report,
not new functionality). Concretely: none of 8b-8e's build-log entries
flagged a missing test as a gap (only missing/deferred UI scope, e.g.
per-trade/per-line simulation overrides, scenario delete with no
backend endpoint) -- so this pass is a review, not expected to add
much. Anything genuinely found gets one small test here rather than a
speculative rewrite of already-passing coverage.

## 3. Explicitly out of scope

- Any further backend feature beyond the two narrow gap-fixes above.
- A full ltree drag-and-drop taxonomy editor -- a plain move-by-picking-
  a-new-parent-id form is enough for "an admin screen", not a
  visual tree-editing UX.
