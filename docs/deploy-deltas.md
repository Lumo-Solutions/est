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
| `backend`/`celery-*` build context | Widened from `context: ../backend` to `context: .. / dockerfile: backend/Dockerfile` (repo root). | `app/takeoff/prompts.py` reads `ai-service/prompts` and `ai-service/schemas` from the container root at runtime; scoping the build context to `backend/` alone meant those files could never be `COPY`'d in at all, and title-block/scale extraction would crash the first time it ran in a real container. See `docs/takeoff-pipeline.md`. |
| Networks | Single `installtec` bridge network added to every service. | SRS §6 relies on Compose's implicit default network; naming it explicitly makes the prod overlay's port-hardening unambiguous. |
| `backend`, `celery-worker` | New `onnxmodels` named volume mounted at `/models` (`$ONNX_MODEL_DIR`). | The embedding backend (`EMBEDDING_BACKEND=onnx`, the default) had `ONNX_MODEL_DIR=/models` set but no volume behind it at all, so `OnnxEmbedder` could never find a model regardless of how it was provisioned. Not mounted into `celery-worker-vlm` or `celery-beat`, which never call `get_embedder()`. |
| `init-buckets` | New one-shot service, `amazon/aws-cli` image, profile `tools` (never started by `make up`). Run via `make init-buckets`. | `deploy/seaweedfs/init-buckets.sh` (unchanged) used `$S3_ENDPOINT`, which is `http://seaweedfs:8333` inside the stack -- a hostname the host machine can't resolve at all -- and also needs the `aws` CLI, which most dev machines don't have installed. Running it inside a container already on the `installtec` network fixes both: no host `aws` CLI needed, and `seaweedfs:8333` resolves correctly. |

### Populating the ONNX embedding model volume

`OnnxEmbedder` (`backend/app/integrations/embeddings.py`) looks for the
model at `$ONNX_MODEL_DIR/<embedding_model with "/" replaced by "_">`, e.g.
`/models/BAAI_bge-small-en-v1.5` for the default `EMBEDDING_MODEL`. Populate
it with `ai-service/embeddings/download_model.py` **on a separate machine
with network access** (it needs `optimum[onnxruntime]` + `huggingface_hub`,
which are intentionally not part of the backend image):

```bash
pip install "optimum[onnxruntime]" huggingface_hub
python ai-service/embeddings/download_model.py --target-dir ./BAAI_bge-small-en-v1.5
```

Then copy that directory's contents into the `onnxmodels` volume (or, for
an air-gapped target, into wherever that volume's underlying storage lives)
so the result is `<volume>/BAAI_bge-small-en-v1.5/{model.onnx,tokenizer.json,...}`.
`download_model.py`'s own default `--target-dir` (when omitted) now matches
this layout — it previously computed just the HuggingFace repo basename
(`bge-small-en-v1.5`, no `BAAI_` prefix), which never matched what the app
looked for; see `ai-service/README.md` for the full air-gapped procedure.
If the model is missing, `OnnxEmbedder.embed()` raises a `FileNotFoundError`
naming the exact expected path rather than crashing the worker opaquely;
`app/workers/tasks/takeoff.py::_embed_drawing_body` catches it, records the
message on the extraction job row, and re-raises so Celery still marks the
task failed.

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
export's group attribute, and `backend/app/cli.py::seed()` (reference data —
trade taxonomy roots, UAE authorities, the default approval policy — is
defined inline in Python there rather than in a separate YAML file; see that
module's docstring for why).

## Local validation actually performed

Unlike the note this section used to carry, Docker Desktop *was* brought up
and used extensively during development, not just for `config --quiet`
validation:

- `docker compose -f deploy/docker-compose.yml config` and the
  `.test`/`.prod` overlays parse correctly.
- The real `backend` image was built from the repo-root context (see the
  build-context delta above) and `alembic upgrade head` was run against a
  live `pgvector/pgvector:pg16` container — all 9 migrations apply cleanly.
- RLS tenant isolation, the audit hash chain (trigger + Python-side
  re-verification), the bi-temporal cost-library exclusion constraint, the
  prequalification exclusion constraint, and the trade-taxonomy ltree
  path/cycle trigger were all exercised with raw SQL as the `installtec_app`
  role directly against a live container.
- A real Keycloak 26 container imported `realm-installtec.json` (roles,
  groups, and clients confirmed via the Admin REST API), issued a token, and
  that token was validated end-to-end through the real FastAPI app,
  producing a real `vendor` row through real RLS. See
  `docs/keycloak-setup.md` for what this did and didn't cover (the
  interactive browser login form specifically hits a Keycloak/Quarkus
  cookie quirk over plain HTTP, documented there, that's independent of
  everything else it validated).
- The full backend test suite (117 tests: unit, integration against
  `testcontainers`-managed Postgres/Redis, and API tests against the real
  ASGI app) passes — `make test` from the repo root, or
  `pytest backend/tests` with a Docker socket available.

This pass caught and fixed several real bugs that a config-only check would
have missed entirely — most notably: every `TenantEntity`-based model wasn't
actually a mapped SQLAlchemy class at all (see `db/base.py`), `app_is_system()`
only bypassed the RLS **read** policy and not writes (see
`docs/security-rls.md`), and the audit-trail's `INSERT ... RETURNING`
interacting with its own RLS `SELECT` policy to break every `estimator`-
initiated action (see `docs/audit-chain.md`). Run `make up` +
`make bootstrap-keycloak` yourself before relying on this stack in a new
environment; the above was validated with ad hoc `docker run`/`docker
compose` invocations during development, not via a from-scratch `make up`.
