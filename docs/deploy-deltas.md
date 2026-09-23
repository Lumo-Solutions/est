# Deployment deltas vs MASTER_SRS.MD §6

`deploy/docker-compose.yml` reproduces the SRS §6 template verbatim for
`postgres`, `redis`, `seaweedfs`, `vllm`, `backend`, `frontend` (same images,
env var names, volumes, ports). Everything below is an addition required to
satisfy SRS §5 (Keycloak, MFA, RLS, TLS, encryption) or to make the stack
actually runnable; each is marked inline in the compose file with a
`# --- addition ---` comment.

| Area | Delta | Reason |
|---|---|---|
| `postgres` | Mounts `./postgres/initdb` for extension/role/keycloak-db bootstrap SQL; adds a healthcheck. | SRS §6 has no provisioning step at all; Module A/B need `vector`, `pg_trgm`, `btree_gist`, `pgcrypto`, `ltree` extensions and the app-vs-migrator role split RLS depends on. |
| `seaweedfs` | `-s3.config=/etc/seaweedfs/s3.json` (SigV4 identity) instead of anonymous S3. | SRS §5.3 requires encryption/access control; the bare SRS command leaves S3 fully open. **Edit `deploy/seaweedfs/s3-identities.json`'s `secretKey` to match `S3_SECRET_KEY` in `.env` before first run** — SeaweedFS reads that file directly and does not expand env vars. |
| `vllm` | Default `vllm` service is now `build: ../ai-service/mock-vllm` (a tiny FastAPI stand-in), not the real image. A second service, `vllm-gpu`, carries the exact SRS image + GPU reservation but is gated behind the `gpu` Compose profile. | No GPU host is provisioned yet (user confirmed). Same service name/port (`vllm:8000`) so `VLLM_API_BASE` never changes in app config. **To switch to real inference:** run `docker compose --profile gpu up -d vllm-gpu`, then set `VLLM_API_BASE=http://vllm-gpu:8000/v1` in `.env` (or repoint the `vllm` service's `build` back to the SRS image once GPU hardware is the default). |
| `keycloak` | New service, `quay.io/keycloak/keycloak:26.0`, `start-dev --import-realm`. | SRS §5.1 requires Keycloak + TOTP MFA; absent from the §6 template entirely. `start-dev` is used for this slice's convenience (auto HTTP, auto-import); switch to `start --optimized` with a real hostname/TLS cert before production (see below). |
| `celery-worker`, `celery-worker-vlm`, `celery-beat` | New services running the Module B ingestion pipeline. | SRS §3 specifies Celery workers for the RAG/AI engine; §6 never wires them up. Split into an `ingest,embed` queue (CPU work) and a `vlm` queue (throttled to 2 concurrency to back-pressure the vision-language model). |
| `backend` | Adds Keycloak, app/migrator DB, Celery, embedding, session, and audit env vars beyond the four SRS ones (all additive — the original four are untouched). | Required for auth, RLS, async ingestion, and the hash-chained audit trail to function. |
| Networks | Single `installtec` bridge network added to every service. | SRS §6 relies on Compose's implicit default network; naming it explicitly makes the prod overlay's port-hardening unambiguous. |

## Role separation (RLS correctness)

`deploy/postgres/initdb/10-roles.sh` creates two Postgres roles:
- `installtec_migrator` — owns the schema; Alembic connects as this role to run DDL.
- `installtec_app` — `NOSUPERUSER NOBYPASSRLS`, **not** the table owner; the running app and all Celery workers connect as this role for every request/task.

This split exists because Postgres table **owners bypass RLS by default** —
if the app connected as the same role that created the tables, every RLS
policy in the system would silently do nothing. Passwords are read from
`APP_DB_PASSWORD`/`MIGRATOR_DB_PASSWORD` in `.env` (dev-mode plaintext via
Compose env; rotate via `ALTER ROLE ... PASSWORD` in production and inject
through a real secrets manager instead of `.env`).

## Keycloak MFA enforcement — current coverage and gap

`realm-installtec.json` enforces TOTP two ways:
1. `requiredActions.CONFIGURE_TOTP` with `defaultAction: true` — every new user must enrol an authenticator app on first login.
2. `otpPolicyType: totp` at the realm level, so once enrolled, OTP is available for step-up (`acr_values=silver`) flows used by `POST /auth/step-up` before approval decisions.

**Known gap:** a user who removes their own OTP credential (Account Console →
Signing In) is not automatically forced to re-enrol on their *next* login by
`requiredActions` alone — that action only fires for users who never
completed it. Closing this fully needs a custom authentication flow
(`browser-mfa`, cloning `browser` with the `OTP Form` execution set to
`REQUIRED` instead of `CONDITIONAL`) bound as the realm's `browserFlow`. This
was deliberately left out of the JSON export in this slice because a
hand-authored authentication-flow export is easy to get subtly wrong and can
break realm import entirely; add it via the Keycloak admin console (Realm
Settings → Authentication) and re-export, or as a follow-up realm patch.

## Production hardening checklist (not done in this slice)

- Switch Keycloak from `start-dev` to `start --optimized`, set a real `KC_HOSTNAME`, and put it behind TLS (via `docker-compose.prod.yml`'s Caddy service).
- Stop publishing `postgres`/`redis`/`seaweedfs`/`keycloak` ports to the host (`docker-compose.prod.yml` already does this with `!reset []`).
- Replace the demo tenant's `tenant_id` attribute value and remove seed users created by `bootstrap.sh`.
- Rotate `s3-identities.json`'s secret key and the `.env` placeholders.
- Add the `browser-mfa` flow described above.

## Demo tenant

`tenant_id = 8f14e45f-ceea-4e97-8d0c-3d3b3f3c1a00`, Keycloak group
`/tenants/demo`. Referenced by `DEMO_TENANT_ID` in `.env.example`, the realm
export's group attribute, and `backend/app/seeds/demo_tenant.yaml`.

## Local validation performed

`docker compose -f deploy/docker-compose.yml config` and the `.test`/`.prod`
overlays were validated for YAML/schema correctness (`docker compose ...
config --quiet`) in this environment. **A live `docker compose up` was not
run** — Docker Desktop's daemon was not running in this session. Run `make up`
and `make bootstrap-keycloak` to do a full smoke test before relying on this
stack; watch in particular for the realm import succeeding
(`docker compose logs keycloak | grep -i realm`) and `pg_isready` passing.
