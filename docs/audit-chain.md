# Immutable, hash-chained audit trail

## The scheme

`audit_events` (migration `0003_audit.py`) is append-only and hash-chained
per `(tenant_id, chain_date)` (UTC day). A `BEFORE INSERT` trigger,
`audit_events_chain_trg()`, computes every chain field — the application
never sets `seq`, `prev_hash`, `event_hash`, `canonical_json`, or
`payload_sha256` itself:

1. `payload_sha256 := sha256(payload::text)` — `jsonb::text` is already
   canonical (deduped keys, deterministic key order, no incidental
   whitespace), so no custom JSON canonicalization is needed.
2. The chain head for `(tenant_id, chain_date)` is fetched with
   `SELECT ... FOR UPDATE` against `audit_chain_heads` (creating the row
   with `ON CONFLICT DO NOTHING` if it's the first event of the day). This
   `FOR UPDATE` is the serialization point — concurrent inserts for the same
   tenant/day queue up here, guaranteeing contiguous `seq` values.
3. `seq := last_seq + 1`, `prev_hash := last_hash` (genesis day starts at
   `last_hash = '0' × 64`).
4. `canonical_json` is built as a **fixed-key** `jsonb_build_object(...)`
   (tenant_id, chain_date, seq, occurred_at, actor_sub, actor_user_id,
   actor_roles (sorted), actor_acr, action, entity_type, entity_id,
   project_id, ip, user_agent, request_id, payload_sha256), cast to text.
5. `event_hash := sha256(prev_hash || '|' || canonical_json)`.
6. The chain head is updated with the new `seq`/`event_hash`.

Storing `canonical_json` verbatim means verification never has to
reproduce Postgres's jsonb serialization in Python — `services/audit.py`
just re-hashes `prev_hash || '|' || canonical_json` and compares.

## Immutability — three independent layers

1. `REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM installtec_app`.
2. `BEFORE UPDATE OR DELETE OR TRUNCATE` triggers that unconditionally
   `RAISE EXCEPTION`.
3. RLS has an `INSERT` policy and a `SELECT` policy — **no `UPDATE` or
   `DELETE` policy exists at all**, so even a role that somehow regained the
   grant would still be denied by RLS.

All three were verified independently and live against a real container
during development (`tests/integration/test_audit_chain_db.py::test_update_is_rejected`
/ `test_delete_is_rejected`), including a version of the test that connects
as the **schema-owning** role (`installtec_migrator`) with the trigger
disabled to hand-craft a tampered row and confirm `verify_chain()` actually
detects it (`test_verify_chain_detects_tampering`) — `installtec_app` itself
can never produce a tampered row to test against, by design.

## The `INSERT ... RETURNING` / RLS interaction (read this before changing `record()`)

`app/services/audit.py::record()` issues a **raw parameterized `INSERT`
with no `RETURNING` clause**. This is deliberate and load-bearing, not a
style choice:

Postgres evaluates a table's `SELECT` policy against any row an
`INSERT ... RETURNING` would hand back to the client. `audit_events`'
`SELECT` policy restricts visibility to `lead_estimator`+ roles (by
design — estimators shouldn't be able to browse the org's full audit log).
SQLAlchemy's ORM `session.add(obj)` + `flush()` **always** appends
`RETURNING` to fetch back server-generated columns (`id`, and via the
trigger, `seq`/`prev_hash`/`event_hash`/etc.). The combination meant that
**any action performed by a plain `estimator`** — a normal, frequent actor;
e.g. requesting an approval — crashed with
`InsufficientPrivilegeError: new row violates row-level security policy for
table "audit_events"`, even though the `INSERT` policy's own `WITH CHECK`
has no role restriction whatsoever.

This was found the hard way: a hand-crafted, fully literal `INSERT`
(matching every column value exactly) succeeded; the *identical* insert
with `RETURNING id` appended failed with the exact same error. Confirmed via
`tests/api/test_approvals_api.py` (an `estimator`-authenticated request
creating an approval). If you're tempted to switch `record()` back to a
plain ORM `session.add()` for convenience, don't — add a regression test
first that authenticates as `estimator` and triggers any audited write.

## Verification

`services/audit.py::verify_chain(session, tenant_id, date_from, date_to)`
streams events ordered by `(chain_date, seq)` and asserts, per day:

- `seq` is contiguous starting at 1
- each row's `prev_hash` equals the previous row's `event_hash` (first row:
  genesis zeros)
- `sha256(prev_hash || '|' || canonical_json) == event_hash`
- `payload_sha256` is present (trusted as computed by the trigger from the
  real stored `jsonb`, not re-derived in Python — `jsonb::text` and
  `json.dumps()` don't format identically byte-for-byte, so re-deriving it
  client-side would produce false positives)

Exposed as `GET /api/v1/audit/verify?date_from=&date_to=` (managing_director
only) and intended to run as a weekly Celery beat task
(`maintenance.verify_audit_chain_all_tenants`) that raises (and thus
surfaces as a failed Celery task) if any tenant's trailing-7-day chain
fails.

## Checkpoints

`audit_checkpoints` records a daily `HMAC-SHA256(AUDIT_CHECKPOINT_HMAC_KEY,
tenant|date|seq|hash)` per tenant/day (`maintenance.write_audit_checkpoints`,
daily beat task). This is a second, cheaper detection mechanism: even if
someone found a way to rewrite the entire `audit_events` table plus
recompute a self-consistent chain (which would require bypassing RLS,
grants, *and* the trigger), they'd also need the HMAC key to forge a
matching checkpoint.
