# Row-Level Security design

## Why RLS, not just app-layer checks

Every business table (all of Module A and Module B except `tenants`, which
has no tenant scope of its own) has `ENABLE ROW LEVEL SECURITY` **and**
`FORCE ROW LEVEL SECURITY`. Postgres table owners bypass RLS by default;
`FORCE` closes that hole. The app and Celery workers connect as
`installtec_app`, a role that:

- does **not** own any table (`installtec_migrator` does, and only Alembic
  connects as that role — see `deploy/postgres/initdb/10-roles.sh`)
- has `NOBYPASSRLS`

`app/services/*` do not filter queries by `tenant_id` for authorization —
the database does that. Services still do `require_roles(...)` checks at
the API layer for fast, clear 403s, but RLS is the actual enforcement
boundary. `tests/integration/test_rls_tenant_isolation.py` and
`test_rls_roles.py` prove this directly: they connect as `installtec_app`
with no application code involved and assert the database itself rejects
cross-tenant reads/writes.

## The GUC contract

Every RLS policy reads four session/transaction-local settings, set once
per request (or once per Celery task) via `app/db/rls.py::set_rls_context`:

| GUC | Meaning | Set from |
|---|---|---|
| `app.tenant_id` | caller's tenant | `RequestContext.tenant_id` |
| `app.user_id` | caller's local user id (== Keycloak `sub` when it's a UUID; see `security/identity.py`) | `RequestContext.user_id` |
| `app.roles` | comma-joined known roles | `RequestContext.roles` |
| `app.is_system` | `'on'` for Celery beat/maintenance/seed contexts | `RequestContext.is_system` |

These are set via **parameterized** `set_config(name, value, true)` calls
(`is_local = true`), never string-interpolated `SET LOCAL` — so there's no
injection risk, and the `true` flag scopes each value to the current
transaction, resetting automatically on commit/rollback. This is what makes
it safe under connection pooling: a pooled connection handed to the next
request starts with no leftover GUC state from the previous one.

`app/db/session.py::get_session()` (the FastAPI dependency) and
`session_scope()` (used by Celery tasks, the OIDC callback, and the seed
CLI) are the **only** sanctioned ways to open a session in this codebase —
both set the GUCs before yielding the session. `session_scope()` is its own
`@asynccontextmanager` generator, not a wrapper around another async
generator via manual `aclose()` — an earlier version did that and it
silently rolled back every write while reporting success (`aclose()` always
throws `GeneratorExit` into the wrapped generator, which SQLAlchemy treats
as an error and rolls back, even on the success path). See the docstring on
`session_scope()` in `db/session.py` for the full explanation; this is why
the seed CLI's writes and every Celery task's writes must go through it
rather than a hand-rolled `async for session in ...: return ...` pattern.

## SQL helper functions (migration 0001 / 0002)

```sql
app_tenant_id()          -- current_setting('app.tenant_id')::uuid
app_user_id()            -- current_setting('app.user_id')::uuid
app_roles()              -- current_setting('app.roles') split on ','
app_has_role(variadic)   -- app_roles() && the given role list
app_is_system()          -- current_setting('app.is_system') = 'on'
app_can_see_project(p)   -- p IS NULL, or is_system, or a director/procurement
                          -- role, or caller is in project_members for p
```

All `STABLE`, `SECURITY INVOKER`. `app_can_see_project()` references
`project_members`, which doesn't exist yet when migration 0001 runs — this
is safe because pre-PG14-style `LANGUAGE sql AS $$...$$` function bodies are
opaque text until first executed, not parsed against the catalog at
`CREATE FUNCTION` time.

## The policy pattern (`app/db/ddl.py::tenant_policies`)

```sql
CREATE POLICY <t>_tenant_read ON <t> FOR SELECT
  USING (app_is_system() OR (tenant_id = app_tenant_id() [AND app_can_see_project(project_id)]));

CREATE POLICY <t>_tenant_write ON <t> FOR INSERT
  WITH CHECK (app_is_system() OR (tenant_id = app_tenant_id() AND app_has_role(...) [AND app_can_see_project(project_id)]));

CREATE POLICY <t>_tenant_update ON <t> FOR UPDATE
  USING (app_is_system() OR (tenant_id = app_tenant_id() AND app_has_role(...) [AND app_can_see_project(project_id)]))
  WITH CHECK (app_is_system() OR tenant_id = app_tenant_id());

CREATE POLICY <t>_tenant_delete ON <t> FOR DELETE   -- only if delete_roles given
  USING (app_is_system() OR (tenant_id = app_tenant_id() AND app_has_role(...) [AND app_can_see_project(project_id)]));
```

**`app_is_system()` bypasses every clause, not just SELECT.** An earlier
version of this helper only added the bypass to the read policy; Celery
beat tasks (certificate-expiry scanning, stale-job reaping) and the seed
CLI write as a system actor with **no role claims at all**, and were
completely locked out of every table until this was fixed. Caught by
`tests/integration/test_rls_tenant_isolation.py::test_system_context_can_write_without_role_claims`.

Project-scoped tables (`projects`, `drawings`, `drawing_sheets`,
`drawing_entities`, `sheet_chunks`, `extraction_jobs`, `approval_requests`,
`approval_steps`) add `app_can_see_project(project_id)`. Two tables
(`approval_steps`, `extraction_jobs`) don't have their own natural
`project_id` — it's **denormalized** from the parent row
(`approval_requests.project_id`, `drawings.project_id`) specifically so the
policy predicate can read it directly without a join, which Postgres RLS
predicates can't do cleanly against a subquery per row at scale.

### `audit_events` is insert-only, not `tenant_policies()`

`app/db/ddl.py::audit_insert_only_policies` is deliberately different: any
authenticated actor may `INSERT` (`WITH CHECK (tenant_id = app_tenant_id()
OR app_is_system())`, no role check), but only `lead_estimator`+ may
`SELECT`. There is no `UPDATE`/`DELETE` policy *at all* — combined with a
`REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM installtec_app` and a
`BEFORE UPDATE OR DELETE` trigger that raises unconditionally, this is
three independent layers making the table append-only.

**Important interaction**: an `INSERT ... RETURNING` under RLS is also
checked against the table's *SELECT* policy for the row being handed back.
`app/services/audit.py::record()` therefore issues a **raw `INSERT` with no
`RETURNING` clause** rather than `session.add(AuditEvent(...))` +
`flush()` — SQLAlchemy's ORM flush always appends `RETURNING` to fetch
server-generated columns, and since a plain `estimator` isn't in
`audit_events`' SELECT-allowed role list, *every* audit-worthy action taken
by an estimator (e.g. requesting an approval) crashed with an RLS violation
on its own audit write, even though the INSERT policy itself has no role
restriction. This was caught by `tests/api/test_approvals_api.py` (an
estimator creating an approval request) and is one of the more subtle
findings from this build — see the docstring on `record()` for the full
explanation.

## Role → write-access matrix (summary; see each migration for the exact list)

| Table family | Write roles | Delete |
|---|---|---|
| `users`, `project_members` | lead_estimator+ | lead_estimator+ |
| `projects` | bd_director, managing_director | managing_director |
| `vendors`, `vendor_contacts`, `vendor_trades` | lead_estimator+ | procurement_head, managing_director |
| `vendor_duplicate_candidates` | lead_estimator+ | — |
| `trade_nodes` | lead_estimator, procurement_head, managing_director | managing_director |
| `authorities`, `certificate_types` | procurement_head, managing_director | — |
| `vendor_certificates`, `vendor_prequalifications`, `certificate_alerts` | procurement_head, lead_estimator, managing_director | — |
| `cost_items`, `cost_item_rates`, `cost_rate_components` | lead_estimator, procurement_head, managing_director | — |
| `approval_policies`, `approval_policy_tiers` | managing_director only | managing_director |
| `approval_requests`, `approval_steps` | any of the 5 roles (service layer gates *decisions* against the step's `required_role`, not RLS) | — |
| `drawings` and everything under it | any of the 5 roles, project-scoped | lead_estimator+ |
| `audit_events` | any authenticated actor (insert-only) | nobody, ever |

## Testing this yourself

`tests/integration/` connects as `installtec_app` (never the owner) against
a real `pgvector/pgvector:pg16` container (via `testcontainers`) and asserts
these properties directly with raw SQL — no application code in the loop.
Run `make test-integration`, or `pytest backend/tests/integration` with a
Docker socket available. `tests/integration/test_migrations.py` also
asserts, generically, that *every* table (except `tenants`) has
`relrowsecurity` and `relforcerowsecurity` set, and that `installtec_app` is
never a table's owner — so a future migration that forgets RLS entirely
fails CI rather than silently shipping.
