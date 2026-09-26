# Module E schema design: post-award contract management (Phase 1, schema readiness)

Per `docs/preconstruction-build-brief.md`'s Phase 7: **schema and design
only, no workflows**. RLS on every table; minimal read (`GET`) endpoints
only, just enough to prove the model is queryable; no write/create service
functions beyond what a later phase's real workflow will add. This doc is
written before the migration, per the brief's own instruction.

## 0. What already exists (reused, not duplicated)

- **`bid_settlements`/`bid_settlement_line_items`** (Module D1) already are
  the "settlement snapshot" a won contract carries forward: each line
  already links `boq_line_item_id` (the BOQ line) and
  `source_quotation_line_item_id` (the accepted vendor quote line) --
  exactly "the settlement snapshot, its BOQ lines and accepted vendor
  quotes" the brief asks a contract to carry. A `contracts` row therefore
  only needs to **point at** a won `BidSettlement` (by id), never
  duplicate its lines into new contract-specific rows.
- **`cost_item_rates`** (Module A, already bi-temporal: `valid_period`
  DATERANGE + `sys_period` TSTZRANGE, `source`/`source_ref`/`confidence`,
  never UPDATEd in place -- see `app/services/costlib.py::record_rate`)
  already IS "the bi-temporal cost library" the brief wants outturn cost
  written back into. It already accepts an arbitrary `source` value and a
  free-text `source_ref` -- **no schema change to this table is needed
  at all**. This phase adds one new enum value (`RateSource.OUTTURN`) and
  a new table (§4) that gives `source_ref` something real and queryable
  to point at (a structured observation with provenance), rather than
  reusing `cost_item_rates` itself for the raw observation, which would
  conflate "the rate a future estimate should use" with "one specific
  contract's actual recorded cost" -- two different things with different
  lifecycles.
- **`quotation_exclusion_flags`** (Module C2, extended in Phase 6 with
  `source_location`/`citation_verified`) is exactly what a live exclusion
  register is "seeded from" -- a register entry optionally carries a FK
  back to the flag it originated from, but stands on its own afterward (a
  register entry can also be added directly, not only from an LLM-detected
  flag).
- **Confirmed nothing in D1 or D2 needs refactoring**: no new column is
  added to `bid_settlements`, `bid_settlement_line_items`,
  `boq_line_items`, `boq_import_batches`, or `quotation_exclusion_flags`.
  Every new FK in this phase points *at* those tables' existing primary
  keys; none of their own rows change shape.

## 1. Contracts (won settlement -> contract)

```
contracts
  id, tenant_id, project_id
  settlement_id       FK -> bid_settlements.id, UNIQUE, ON DELETE RESTRICT   -- one contract per settlement; never delete a settlement a contract points at
  contract_ref        varchar, unique per tenant                             -- human-facing reference, assigned like rfq_ref (a DB trigger; see migration)
  status               draft | active | closed
  awarded_at           timestamptz, nullable
  created_by, created_at (via TenantEntity)
```

Deliberately **not** copying `tender_total`/vendor/BOQ data onto
`contracts` itself -- every one of those is already reachable through
`settlement_id` -> `bid_settlements`/`bid_settlement_line_items`, and
duplicating it would create a second source of truth that could drift
from the settlement the moment anyone reads it. `contracts` is a thin
"this settlement is now a live contract" anchor other Module E tables key
off of.

`ON DELETE RESTRICT` on `settlement_id` (not `CASCADE`): a settlement that
has become a real contract must never be deletable out from under it by
an unrelated D1 cleanup action.

## 2. BOQ and contract revisions, with lineage

Two independent lineages -- a client can reissue a BOQ before a contract
even exists; a contract can be varied after award. Both use the same
self-referencing-parent shape.

```
boq_revisions
  id, tenant_id, project_id
  revision_no          integer
  parent_revision_id   FK -> boq_revisions.id, nullable (self)
  import_batch_id       FK -> boq_import_batches.id, nullable, ON DELETE SET NULL   -- which D2 import produced this revision, if any
  reason                text
  created_by, created_at

contract_revisions
  id, tenant_id, contract_id FK -> contracts.id
  revision_no           integer
  parent_revision_id    FK -> contract_revisions.id, nullable (self)
  reason                text
  created_by, created_at

contract_variations
  id, tenant_id, contract_id FK -> contracts.id
  revision_id            FK -> contract_revisions.id                          -- which revision this variation was priced against
  variation_ref           varchar, unique per tenant (trigger-assigned)
  description              text
  delta_amount              numeric(18,2), nullable                            -- the priced change; null while still a scope-only proposal
  status                    proposed | approved | rejected
  created_by, created_at
```

`boq_revisions` deliberately carries no FK *from* `boq_line_items` (no
`revision_id` column added to that existing table) -- a real "which
revision is this line on" workflow is Phase-2-of-Module-E's job, and
adding that column now, unused, would be exactly the kind of speculative
schema change the brief's "no workflows" scope excludes. `import_batch_id`
alone is enough today to associate a revision with the import that
produced it, which is all a read-only proof-of-model needs.

## 3. Live exclusion register

```
exclusion_register
  id, tenant_id, project_id
  contract_id                FK -> contracts.id, nullable                     -- an entry can exist pre-contract, scoped by project alone
  source_exclusion_flag_id    FK -> quotation_exclusion_flags.id, nullable, ON DELETE SET NULL
  description                  text
  status                        open | resolved | accepted_risk
  resolution_note                text, nullable
  resolved_by, resolved_at        nullable
  created_by, created_at
```

"Live" means this table, not `quotation_exclusion_flags` itself, is what
a contract-management screen reads from -- a register entry's own
`status` tracks resolution independently of whatever happens to the
originating flag (which stays exactly what Module C2 already does with
it: reviewed/acknowledged per-quotation, never mutated by anything this
phase adds).

## 4. Outturn (actual) cost, with provenance

```
outturn_cost_observations
  id, tenant_id, project_id
  contract_id              FK -> contracts.id
  boq_line_item_id           FK -> boq_line_items.id, nullable                 -- which line this actual cost was observed against, if line-specific
  cost_item_id                 FK -> cost_items.id, nullable                    -- which cost-library item this should eventually rate, if known
  observed_unit_cost             numeric(14,4)
  observed_quantity                numeric(18,4), nullable
  currency                          varchar(3)
  observed_at                        date
  source_note                          text                                     -- e.g. "final account", "site instruction #4"
  recorded_by, recorded_at (via TenantEntity's created_by/created_at)
  written_back_rate_id                  FK -> cost_item_rates.id, nullable, ON DELETE SET NULL   -- set once a (future, Phase-2) workflow actually calls record_rate() with source=outturn
```

`written_back_rate_id` is the seam a later phase's real write-back
workflow fills in -- this phase adds the column and the FK target so that
workflow needs zero schema change of its own, satisfying "must natively
support... outturn cost write-backs... without major schema refactoring";
it does **not** implement that workflow (no service function calls
`record_rate()` from this phase's code).

`RateSource` (`app/core/enums.py`) gains one new value, `OUTTURN = "outturn"`,
so a future write-back's `cost_item_rates.source` has a real, honest label
distinct from `manual`/`quotation`/`award`/`index_adjustment`/`import`.

## 5. RLS

Every new table: `enable_rls` + `tenant_policies`, project-scoped
(`contracts`/`boq_revisions`/`exclusion_register`/`outturn_cost_observations`
carry `project_id` directly; `contract_revisions`/`contract_variations`
are scoped through their `contract_id` -- see migration for the exact
`project_scoped` wiring, following `bid_settlement_line_items`' own
precedent of a table with no direct `project_id` column still reachable
via `project_scoped=True`'s `app_can_see_project(project_id)` check where
`project_id` is present, or plain tenant-scoping where it's genuinely one
step removed).

Write roles: same operational tier as D1 (`lead_estimator`,
`procurement_head`, `bd_director`, `managing_director`) for every new
table -- Module E rows are written by the same estimating/commercial team
that already touches settlements and BOQs; no new role tier invented.
Since this phase adds no write endpoints, these policies exist for
correctness/future-readiness, not because anything calls them yet.

## 6. Endpoints (read-only, "prove the model")

- `GET /projects/{id}/contracts`, `GET /contracts/{id}`
- `GET /contracts/{id}/revisions`, `GET /contracts/{id}/variations`
- `GET /projects/{id}/boq-revisions`
- `GET /projects/{id}/exclusion-register` (optional `status` filter)
- `GET /projects/{id}/outturn-cost-observations`

No `POST`/`PATCH` anywhere in this phase -- rows are seeded directly (by
a later phase's workflow, or by a test/dev-sim script talking straight to
the ORM) until that workflow exists.

## 7. Testing plan

- Integration only (there is no pure logic to unit-test in a schema-only
  phase): RLS isolation for every new table at the lowest allowed role
  (`lead_estimator`, matching D1's own precedent) plus a denied
  non-member; a lineage query resolving a `contract_revisions` parent
  chain correctly; `contracts.settlement_id` uniqueness enforced (a
  second contract can't point at the same settlement); the read endpoints
  return what was seeded.

## 8. Explicitly out of scope for this phase

- Any state-machine/approval logic for contracts, revisions, variations,
  or exclusion-register resolution -- Phase 2 of Module E.
- The actual outturn-cost write-back workflow (reading
  `outturn_cost_observations` and calling `costlib_service.record_rate()`)
  -- the schema is ready for it; the workflow itself is not this phase's
  job.
- Any UI (Phase 8 of this build).
