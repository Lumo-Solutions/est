# Module A — Data Model Reference

This documents the agreed shape of Module A's schema (Enterprise Data &
Governance Core). It is the design reference; the authoritative source is
the SQLAlchemy models under `backend/app/models/` and the Alembic migrations
under `backend/app/migrations/versions/` — minor column names may drift
slightly from this document during implementation, but the entities,
relationships, and key constraints below should hold.

Conventions applying to every table unless noted: `id UUID` primary key
(`gen_random_uuid()`), `tenant_id UUID NOT NULL` foreign key to `tenants`,
`created_at`/`updated_at TIMESTAMPTZ`, `created_by`/`updated_by UUID`. Every
table has PostgreSQL Row-Level Security **enabled and forced**
(`FORCE ROW LEVEL SECURITY`, so even the owning role is subject to policy);
see `docs/security-rls.md` for the policy pattern.

## Tenancy & projects

| Table | Purpose | Key columns |
|---|---|---|
| `tenants` | One row per contractor organization sharing the deployment. | `slug` (unique), `name`, `base_currency` |
| `users` | Local mirror of Keycloak identities, upserted on login. | `keycloak_sub` (unique, source of truth), `email`, `roles_cache` (display only — authorization always derives from the JWT, never this column) |
| `projects` | A tender/bid opportunity. | `code` (unique per tenant), `status` (prospect/tendering/submitted/awarded/lost/archived), `client_name`, `submission_due_at` |
| `project_members` | Drives project-scoped RLS visibility. | `project_id`, `user_id`, `project_role` |

## Configurable trade taxonomy

| Table | Purpose | Key columns |
|---|---|---|
| `trade_nodes` | Hierarchical trade categories (earthworks, asphalt, concrete, MEP, utilities, ...). | `parent_id` (self FK), `path` (`LTREE`, maintained by trigger on reparent), `code`, `level`, `attributes JSONB` |

The `path` column enables efficient subtree queries (`path <@ '1.2'`) and
cycle-safe move/reparent operations (a trigger rejects a move that would
make a node its own descendant).

## Vendor master & duplicate detection

| Table | Purpose | Key columns |
|---|---|---|
| `vendors` | Unified vendor repository. | `legal_name`, `normalized_name` (trigram-indexed), `trade_license_no`, `normalized_license`, `contact_fingerprint` (sha256 of email domain + phone + license), `status` |
| `vendor_contacts` | Contacts per vendor. | `vendor_id`, `email`, `phone`, `is_primary` |
| `vendor_trades` | Vendor ↔ trade taxonomy mapping. | `vendor_id`, `trade_node_id`, `is_primary` |
| `vendor_duplicate_candidates` | Detected possible duplicates awaiting resolution. | `vendor_a_id`, `vendor_b_id`, `score NUMERIC(5,4)`, `signals JSONB`, `status` (open/confirmed/not_duplicate/merged) |

Duplicate scoring blocks candidates in SQL via trigram similarity, then
scores them in Python (`rapidfuzz`) on name/license/address/phone/email/TRN
signals; see `docs/architecture.md` and `backend/app/services/dedupe.py`.

## Prequalification & statutory register

| Table | Purpose | Key columns |
|---|---|---|
| `authorities` | Issuing bodies (Dubai Municipality, RTA, DEWA, Civil Defence, ...). | `code`, `name`, `jurisdiction` |
| `certificate_types` | Certificate types per authority. | `authority_id`, `validity_months`, `warn_days_before` |
| `vendor_certificates` | Held certificates with expiry tracking. | `certificate_no`, `issue_date`, `expiry_date`, `status` (derived nightly) |
| `vendor_prequalifications` | **Effective-dated** approval status. | `status`, `effective_period DATERANGE`, `scope_trade_node_id` |
| `certificate_alerts` | Expiry alerts raised by the nightly scan job. | `vendor_certificate_id`, `alert_type`, `due_date` |

`vendor_prequalifications` carries a PostgreSQL `EXCLUDE USING gist`
constraint over `(vendor_id, scope_trade_node_id, effective_period)` so two
statuses can never overlap in time for the same vendor/scope — a status
change is always "close current row, open new row" in one transaction,
which is what makes historical reconstruction (A-10) possible: query the
row whose `effective_period` contains the date of interest.

## Master cost library (bi-temporal)

| Table | Purpose | Key columns |
|---|---|---|
| `cost_items` | Cost item catalog (material/labour/equipment/subcontract/composite/indirect). | `code` (unique per tenant), `uom`, `trade_node_id` |
| `cost_item_rates` | **Bi-temporal** unit rate history. | `valid_period DATERANGE` (when the rate applies in reality), `sys_period TSTZRANGE` (when the system believed it — never updated in place, only closed and superseded), `total_rate`, `scope_key` |
| `cost_rate_components` | Component-level decomposition of a rate. | `component_type` (material/labour/equipment/subcontractor/indirect), `quantity_per_uom`, `unit_cost`, `waste_factor`, `amount` (generated column) |

Two independent time axes: **valid time** (the real-world period a rate is
correct for) and **system time** (when the system recorded that belief).
Correcting a past mistake never mutates history — it closes the old system
row and inserts a new one — so `cost_item_rates` can answer "what rate did
we believe was correct for material X on 1 June 2025, as of what we knew on
1 March 2025" (A-10 historical reconstruction), which is exactly the query
`costlib_rate_as_of(item, scope, valid_on, known_at)` answers.

## Approval workflows (multi-tier threshold routing)

| Table | Purpose | Key columns |
|---|---|---|
| `approval_policies` | Named, versioned policy per entity type. | `entity_type`, `version`, `mode` (sequential vs. highest-tier-only) |
| `approval_policy_tiers` | Amount-banded tiers within a policy. | `min_amount`, `max_amount`, `required_role`, `requires_mfa` |
| `approval_requests` | An in-flight or completed approval. | `entity_type`, `entity_id`, `amount`, `policy_id` + `policy_version` (frozen at request time), `status` |
| `approval_steps` | Per-tier decision record. | `required_role`, `status`, `decided_by`, `decided_ip`, `decided_acr` (proves MFA/step-up was satisfied at decision time) |

Roles routed through tiers are the five SRS roles: `estimator`,
`lead_estimator`, `procurement_head`, `bd_director`, `managing_director`.
`approval_requests` freezes `policy_version` so editing a policy later never
rewrites the history of requests already routed under the old version.

## Immutable, hash-chained audit trail

| Table | Purpose | Key columns |
|---|---|---|
| `audit_chain_heads` | One row per `(tenant_id, chain_date)`; the serialization point for chain appends. | `last_seq`, `last_hash` |
| `audit_events` | Append-only log of create/read/update/delete/approve/reject/export/login/... actions. | `seq`, `occurred_at`, `actor_user_id`, `actor_roles`, `action`, `entity_type`/`entity_id`, `ip_address`, `payload JSONB`, `payload_sha256`, `prev_hash`, `event_hash`, `canonical_json` |
| `audit_checkpoints` | Periodic HMAC-signed checkpoints for tamper detection against wholesale table replacement. | `head_seq`, `head_hash`, `hmac` |

Every `audit_events` row is chained to the previous one for its tenant/day:
`event_hash = sha256(prev_hash \|\| '\|' \|\| canonical_json)`, computed in a
`BEFORE INSERT` database trigger (not application code), so no writer —
application, ad-hoc script, or migration — can produce an audit row outside
the chain. `UPDATE`/`DELETE`/`TRUNCATE` on `audit_events` are blocked at
three independent layers: revoked grants, a trigger that raises on mutation,
and the absence of any RLS `UPDATE`/`DELETE` policy. See
`docs/audit-chain.md` for the exact canonicalization and verification
procedure.

## Module E readiness (schema hooks only, no logic yet)

No dedicated tables exist yet for post-award contract management. The
hooks already in place so it can be added without a major refactor:
- `cost_item_rates.source = 'award'` + `source_ref` already supports writing
  outturn (as-awarded) costs back into the rate library as a normal bi-temporal
  entry, distinguishable from manually-entered or quoted rates.
- `projects.status` includes `awarded`, giving Module E a natural point to
  hang a future `contracts` table off of via `project_id`.
- `cost_items.attributes JSONB` can carry contract/exclusion-register mapping
  keys without a schema change.
