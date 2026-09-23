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
make up            # docker compose up (dev overlay, hot reload)
make migrate        # alembic upgrade head
make seed           # demo tenant + taxonomy + authorities
make bootstrap-keycloak
```

Backend: http://localhost:8001/docs
Keycloak: http://localhost:8080

## Status: Slice 1

Implemented: Module A (vendor master & duplicate detection, trade taxonomy,
prequalification/statutory register, bi-temporal cost library, approval
workflows, hash-chained audit trail) with PostgreSQL RLS; Keycloak OIDC
authentication with TOTP MFA and a BFF session model; Module B drawing
ingestion, title-block/scale extraction via vLLM, and pgvector embeddings.

Deferred (see `docs/architecture.md`): BOQ reconciliation/RAG retrieval,
DXF geometric intelligence (alignments, volumes, pipe topology, typology
clustering), Modules C/D/E, and the production React UI.
