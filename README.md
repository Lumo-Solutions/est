# INSTALLTEC AI Pre-Construction, Estimation & Procurement Platform

Self-hosted, air-gap-ready platform for mid-market regional contractors. See
`MASTER_SRS.MD` for the full requirements spec and `docs/architecture.md` for
a system overview.

## Repository layout

```
backend/      FastAPI app, SQLAlchemy models, Alembic migrations, Celery workers
frontend/     React 18 + Vite + Tailwind + AG Grid (placeholder in slice 1)
ai-service/   vLLM prompt templates, JSON schemas, embedding model provisioning
deploy/       docker-compose stack, .env.example, Keycloak realm, Postgres init
docs/         architecture, data model, security/RLS, audit chain, runbooks
```

## Quickstart (dev)

```bash
cp deploy/.env.example deploy/.env
# edit deploy/.env with local secrets
make up               # docker compose up (dev overlay, hot reload)
make migrate          # alembic upgrade head
make seed             # demo tenant + taxonomy + authorities
make bootstrap-keycloak
make init-buckets     # creates the SeaweedFS drawings bucket
```

Backend: http://localhost:8001/docs
Keycloak: http://localhost:8080
Postgres (from the host, e.g. `psql`): `localhost:5433` — moved off the
default 5432 to avoid clashing with a locally-installed Postgres or another
project's stack; nothing inside the compose network changes.

**Testing the API without a browser:** the interactive Keycloak login form
doesn't work over plain HTTP locally (see `docs/keycloak-setup.md`). Run
`make dev-token` to get a real bearer token for a seeded demo user
(**dev only**, never against a shared/production Keycloak):

```bash
make dev-token
curl -s -H "Authorization: Bearer $(cat .dev-token)" http://localhost:8001/api/v1/auth/me
```

**Windows:** run all `make`/shell commands from **Git Bash**, not
PowerShell or cmd.exe — the Makefile and `deploy/` scripts are POSIX shell.
See `docs/deploy-deltas.md` for the Git Bash `MSYS_NO_PATHCONV` note (needed
by any `docker exec`/`docker run` call that takes an absolute container
path, e.g. `/opt/keycloak/bin/kcadm.sh`).

The `frontend` compose service is gated behind the `frontend` Compose
profile and skipped by `make up` until `frontend/` exists (Phase 5); enable
it explicitly with `docker compose --profile frontend up -d` once it does.

## Status: Slice 1

Implemented: Module A (vendor master & duplicate detection, trade taxonomy,
prequalification/statutory register, bi-temporal cost library, approval
workflows, hash-chained audit trail) with PostgreSQL RLS; Keycloak OIDC
authentication with TOTP MFA and a BFF session model; Module B drawing
ingestion, title-block/scale extraction via vLLM, and pgvector embeddings.

Deferred (see `docs/architecture.md`): BOQ reconciliation/RAG retrieval,
DXF geometric intelligence (alignments, volumes, pipe topology, typology
clustering), Modules C/D/E, and the production React UI.
