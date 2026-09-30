.PHONY: check-ai-env dev-seed-ai-demo dev-seed-ai-demo-quotes dev-ai-demo-pack ai-eval ai-smoke dwg-fixtures dev-mfa-off dev-mfa-on up down logs migrate revision seed bootstrap-keycloak dev-token dev-simulate-quotes dev-simulate-settlement dev-simulate-takeoff-pdf dev-simulate-typology-pdf dev-simulate-semantic-matching dev-simulate-module-e-schema dev-simulate-e2e dev-clean-demo-data download-embedding-model init-buckets render-s3-identities check-s3-identities test test-unit test-integration test-api test-all lint fmt typecheck build

# The DWG converter sandbox (deploy/dwg-converter, ODA File Converter, INTERNAL
# USE ONLY) is built from a local .deb that is never committed; enable its
# compose profile only on machines that hold it. `make up` therefore works
# unchanged everywhere, and DWG uploads report "converter not installed"
# where the .deb is absent.
# 1 when this machine holds the converter package: then missing DWG fixtures FAIL the
# tests instead of skipping them.
DWG_REQUIRE=$(if $(wildcard deploy/vendor/oda/ODAFileConverter*.deb),1,0)
DWG_PROFILE=$(if $(wildcard deploy/vendor/oda/ODAFileConverter*.deb),--profile dwg,)
COMPOSE=docker compose $(DWG_PROFILE) -f deploy/docker-compose.yml -f deploy/docker-compose.override.dev.yml --env-file deploy/.env
# -p pins its own Compose project name -- without one, Compose defaults to
# the directory holding the compose file ("deploy"), the SAME default the
# main COMPOSE above gets. Running this stack while the main dev stack is
# up then silently RECREATES postgres/redis/seaweedfs under this file's
# ephemeral (tmpfs) definitions, destroying those containers -- happened
# once during Phase 2 verification (see docs/takeoff-pipeline.md). This
# stack has no named volumes (tmpfs only), so an explicit -p is the whole
# fix -- no data-continuity concern the way giving the main COMPOSE one
# would have (its volumes -- pgdata/swdata/onnxmodels -- aren't given
# explicit `name:` overrides, so they're project-name-prefixed; changing
# that project name would silently start every `make up` against brand
# new, empty volumes instead of the real dev data).
TEST_PROJECT_NAME=installtec-test
COMPOSE_TEST=docker compose -p $(TEST_PROJECT_NAME) -f deploy/docker-compose.test.yml --env-file deploy/.env

# Renders deploy/seaweedfs/s3-identities.json from its .template (envsubst
# against deploy/.env) so S3_SECRET_KEY never needs manually copying into a
# second file, and every S3_BUCKET_* setting gets its IAM grant from the
# same source of truth instead of a hard-coded bucket name in the template
# -- see deploy/seaweedfs/s3-identities.json.template and
# check-identity-grants.sh for the bug this fixed. The rendered file is
# gitignored; only the template is tracked. Re-run any time S3_SECRET_KEY
# or an S3_BUCKET_* value changes in deploy/.env.
#
# SeaweedFS only reads this file at container start -- editing it on disk
# has no effect on an already-running seaweedfs until it restarts, which
# `docker compose up -d` alone will NOT do for a bind-mounted file with no
# other config change (silent AccessDenied trap otherwise). This target
# restarts it itself whenever the container is already up.
render-s3-identities:
	@test -f deploy/.env || { echo "deploy/.env not found -- run: cp deploy/.env.example deploy/.env" >&2; exit 1; }
	set -a; \
	. deploy/.env; \
	: "$${S3_BUCKET_DRAWINGS:=installtec-drawings}"; \
	: "$${S3_BUCKET_PROCUREMENT:=installtec-procurement}"; \
	set +a; \
	envsubst '$$S3_ACCESS_KEY $$S3_SECRET_KEY $$S3_BUCKET_DRAWINGS $$S3_BUCKET_PROCUREMENT' \
	  < deploy/seaweedfs/s3-identities.json.template \
	  > deploy/seaweedfs/s3-identities.json
	bash deploy/seaweedfs/check-identity-grants.sh deploy/.env deploy/seaweedfs/s3-identities.json
	@if [ -n "$$($(COMPOSE) ps -q seaweedfs 2>/dev/null)" ]; then \
	  echo "s3-identities.json (re-)rendered -- restarting seaweedfs so it picks up the new grants"; \
	  $(COMPOSE) restart seaweedfs; \
	fi

# Standalone version of the check embedded in render-s3-identities, for CI
# or verifying an already-rendered file without re-rendering/restarting.
check-s3-identities:
	bash deploy/seaweedfs/check-identity-grants.sh deploy/.env deploy/seaweedfs/s3-identities.json

# Renders docker-compose.yml + docker-compose.prod.yml's real merged config
# (no containers started) and asserts every backend-family service actually
# gets APP_ENV=production/PRODUCTION_MODE=true out of it. See
# deploy/check-prod-app-env.sh and docs/deploy-deltas.md.
check-prod-app-env:
	bash deploy/check-prod-app-env.sh deploy/.env

up: render-s3-identities
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=200

migrate:
	$(COMPOSE) exec backend alembic upgrade head

revision:
	$(COMPOSE) exec backend alembic revision --autogenerate -m "$(m)"

seed:
	$(COMPOSE) exec backend python -m app.cli seed --tenant demo

bootstrap-keycloak:
	set -a; . deploy/.env; set +a; bash deploy/keycloak/bootstrap.sh

# DEV ONLY -- turns MFA off / back on: sets DEV_DISABLE_MFA in deploy/.env,
# re-runs bootstrap-keycloak (login OTP) and recreates the backend/workers
# (step-up bypass). Refuses to turn it off unless APP_ENV is exactly dev/test.
# See deploy/keycloak/dev-set-mfa.sh and docs/keycloak-setup.md.
dev-mfa-off:
	bash deploy/keycloak/dev-set-mfa.sh true

dev-mfa-on:
	bash deploy/keycloak/dev-set-mfa.sh false

# DEV ONLY -- prints a bearer token for a seeded demo user (default
# estimator1) into .dev-token, e.g. `make dev-token`, or
# `bash deploy/keycloak/dev-token.sh <user> <pass>` directly for a
# different seeded user/role. See that script's header comment.
dev-token:
	set -a; . deploy/.env; set +a; bash deploy/keycloak/dev-token.sh

# DEV ONLY -- sends six simulated vendor quote replies into GreenMail
# against a demo RFQ (creating one if none exists yet) and enqueues an
# immediate IMAP poll instead of waiting for celery-beat's 60s schedule.
# Refuses outright if APP_ENV=production or IMAP_HOST isn't the recognized
# dev host -- see app/cli.py::simulate_quotes. See
# docs/procurement-quotation-ingestion.md for what each scenario exercises.
dev-simulate-quotes:
	$(COMPOSE) exec backend python -m app.cli simulate-quotes

# Module D1 end-to-end against the real dev stack -- see
# app/cli.py::simulate_settlement and docs/module-d1-plan.md.
dev-simulate-settlement:
	$(COMPOSE) exec backend python -m app.cli simulate-settlement

# Module B Phase 4a end to end against the real Celery ingest pipeline --
# requires TAKEOFF_PERSIST_GEOMETRY=true in deploy/.env (default false;
# see app/cli.py::simulate_takeoff_pdf and docs/module-b-phase4-plan.md §4a).
dev-simulate-takeoff-pdf:
	$(COMPOSE) exec backend python -m app.cli simulate-takeoff-pdf

# Module B Phase 4c end to end -- typology cluster detect/confirm/rollup
# against a real 2-sheet synthetic PDF (see app/cli.py::simulate_typology_pdf).
dev-simulate-typology-pdf:
	$(COMPOSE) exec backend python -m app.cli simulate-typology-pdf

# Module B/C Phase 5 end to end -- suggestion ranking + RAG re-ranking.
# Degrades gracefully (prints which path it's exercising) if the ONNX
# model isn't provisioned -- see `make download-embedding-model`.
dev-simulate-semantic-matching:
	$(COMPOSE) exec backend python -m app.cli simulate-semantic-matching

# Module E Phase 1 end to end -- schema readiness only (no workflow), so
# this seeds rows by direct ORM construction and reads them back through
# the real GET endpoints' service functions. Requires a WON settlement in
# the demo tenant -- run `make dev-simulate-settlement` first.
dev-simulate-module-e-schema:
	$(COMPOSE) exec backend python -m app.cli simulate-module-e-schema

# Phase 9: the full end-to-end lifecycle (upload a DXF and a vector PDF ->
# takeoff -> BOQ import -> reconcile -> procurement package -> RFQ (real
# dispatch) -> a real simulated vendor quote -> accept -> bid-level ->
# settle (submit, a *different* user approves) -> export both ways ->
# win/loss) against a dedicated project (E2E-SIM) that `make
# dev-clean-demo-data` can remove on its own, without touching any other
# simulate-*'s own fixtures.
dev-simulate-e2e:
	$(COMPOSE) exec backend python -m app.cli simulate-e2e

# docs/ui-qa-brief.md Phase 1: manual-QA-only demo data on its own QA-DEMO
# project -- a rejected settlement, a lost-outcome settlement, a vendor
# duplicate-candidate pair, and a vendor with expired/expiring-soon/valid
# certificates. Cleaned by `make dev-clean-demo-data` alongside E2E-SIM.
dev-seed-qa-demo-data:
	$(COMPOSE) exec backend python -m app.cli seed-qa-demo-data

# docs/ai-provider-brief.md Phase 5: synthetic UAE infrastructure data for the AI features -- a ~150-item cost
# library with rate history, 20 vendors (some with expiring/lapsed prequalification), 15 past tenders with
# outcomes. Tagged, so `make dev-clean-demo-data` removes it. Idempotent. Needs `make seed` first.
dev-seed-ai-demo:
	$(COMPOSE) exec backend python -m app.cli seed-ai-demo

# Writes the synthetic tender pack (DXF + vector-PDF drawings, Excel and PDF BOQ, spec, addendum, contract) to
# ./.ai-demo-pack/ on the host, ready to drop into a project's Tender documents tab.
dev-ai-demo-pack:
	export MSYS_NO_PATHCONV=1; \
	$(COMPOSE) exec backend rm -rf /tmp/ai-demo-pack && \
	$(COMPOSE) exec backend python -m app.cli write-ai-demo-pack --out /tmp/ai-demo-pack && \
	rm -rf .ai-demo-pack && mkdir -p .ai-demo-pack && \
	docker cp installtec_backend:/tmp/ai-demo-pack/. .ai-demo-pack/

# Accepted vendor quotes for project AI-DEMO's BOQ lines (run after the BOQ has been imported).
dev-seed-ai-demo-quotes:
	$(COMPOSE) exec backend python -m app.cli seed-ai-demo-quotes --project AI-DEMO

# Evaluation harness: golden sets for every AI task, accuracy / cost / latency per provider and model, written to
# docs/ai-eval/. Runs against the provider in AI_PROVIDER (mock by default, so it works without a key); pass
# PROVIDER=anthropic (etc.) with the key in deploy/.env to evaluate a real one.
ai-eval:
	export MSYS_NO_PATHCONV=1; \
	$(COMPOSE) exec -e AI_PROVIDER=$${PROVIDER:-mock} backend python -m app.ai.eval --out /tmp/ai-eval && \
	mkdir -p docs/ai-eval && docker cp installtec_backend:/tmp/ai-eval/. docs/ai-eval/

# Fails if a worker AI_* key is not also passed to the backend service (they keep separate environment lists).
check-ai-env:
	bash deploy/check-ai-env.sh

# One tiny real call per task; skipped with a clear message when no key is configured.
ai-smoke:
	$(COMPOSE) exec backend python -m app.ai.smoke

# Deletes what `make dev-simulate-e2e` and `make dev-seed-qa-demo-data` created above.
dev-clean-demo-data:
	$(COMPOSE) exec backend python -m app.cli clean-demo-data

# DEV ONLY -- provisions the ONNX embedding model into the `onnxmodels`
# named volume the real backend/celery-worker containers read from
# ($ONNX_MODEL_DIR=/models). Requires network access (downloads from
# HuggingFace) -- not run by `make up`, an explicit opt-in step, same
# posture as bootstrap-keycloak. Module B/C Phase 5 -- see
# docs/deploy-deltas.md's "Populating the ONNX embedding model volume"
# and docs/module-b-c-phase5-plan.md §1. For an air-gapped target, run
# ai-service/embeddings/download_model.py on a separate machine with
# network access instead and copy its output into that machine's own
# equivalent of this volume.
# --target-dir/-v both use $(CURDIR)-relative paths, not /tmp/... -- found
# live on Windows/Git Bash: a bare `/tmp/onnx-model-export` gets silently
# reinterpreted two DIFFERENT ways by the two native (non-MSYS) processes on
# this one line -- Python's pathlib treats a leading "/" as "root of the
# current drive" (so the exporter actually wrote to C:\tmp\onnx-model-export),
# while `docker run -v /tmp/onnx-model-export:/src` (Docker Desktop) resolves
# a bare POSIX path against its own WSL VM filesystem, not the Windows host
# -- so the bind mount was empty and `cp -r` silently copied nothing into the
# named volume, with no error at any step. The backend/workers then found an
# empty ONNX_MODEL_DIR and every embed_drawing task failed forever (the
# "GEO-TEST stuck in extracting" root cause -- see docs/takeoff-pipeline.md).
# $(CURDIR)/.onnx-model-export is an unambiguous, real Windows path both
# processes resolve identically; MSYS_NO_PATHCONV=1 (same as bootstrap.sh)
# additionally stops Git Bash itself from rewriting it a third way.
download-embedding-model:
	pip install --quiet "optimum[onnxruntime]" huggingface_hub
	export MSYS_NO_PATHCONV=1; \
	python ai-service/embeddings/download_model.py --target-dir "$(CURDIR)/.onnx-model-export" && \
	docker run --rm -v deploy_onnxmodels:/models -v "$(CURDIR)/.onnx-model-export:/src" alpine \
	  sh -c "mkdir -p /models/BAAI_bge-small-en-v1.5 && cp -r /src/. /models/BAAI_bge-small-en-v1.5/" && \
	rm -rf "$(CURDIR)/.onnx-model-export"

# Runs inside a container on the compose network -- see the `init-buckets`
# service comment in deploy/docker-compose.yml for why (host can't resolve
# `seaweedfs` and may not have the `aws` CLI installed).
init-buckets:
	$(COMPOSE) --profile tools run --rm init-buckets

lint:
	cd backend && ruff check .

fmt:
	cd backend && ruff format .

typecheck:
	cd backend && mypy app

# `cd backend && python -m pytest` (the obvious thing to do here) needs a
# host Python matching backend/pyproject.toml's `>=3.12,<3.13` pin, plus
# every `[project.optional-dependencies].dev` package installed into it. On
# a fresh Windows dev machine neither is guaranteed. So this runs pytest
# inside a throwaway `python:3.12-slim` container instead: matches the
# pinned interpreter exactly regardless of host setup, and needs nothing
# besides Docker. tests/unit has no DB/Redis/Docker-socket dependency at
# all (unlike test-integration below), so this needs no network/socket
# mounts -- just backend/ and the sibling ai-service/ (app/takeoff/prompts.py
# and app/procurement/prompts.py both resolve prompts/schemas relative to
# the container root, same layout the real backend image uses -- see
# backend/Dockerfile). Found and fixed while verifying Module C2: this
# target previously just ran `cd backend && python -m pytest`, which only
# ever worked by coincidence on a host Python that happened to have the
# dev extras pre-installed.
test-unit: dwg-fixtures
	export MSYS_NO_PATHCONV=1; \
	docker run --rm \
	  -v "$(CURDIR)/backend:/workspace" \
	  -v "$(CURDIR)/ai-service:/ai-service" \
	  -v installtec-test-pip-cache:/root/.cache/pip \
	  -e REQUIRE_DWG_FIXTURES=$(DWG_REQUIRE) \
	  -w /workspace \
	  python:3.12-slim \
	  bash -c "pip install --quiet -e '.[dev]' && python -m pytest tests/unit -q"

# tests/conftest.py's DB/Redis fixtures use `testcontainers` to spin up
# their OWN separate, ephemeral containers (never docker-compose.test.yml's
# services -- see that file's own port-policy comment), which is *why* the
# container below needs the host's Docker socket mounted in
# (Docker-outside-of-Docker): testcontainers talks to the same Docker
# daemon the host uses to run sibling containers next to it, not to
# anything nested inside this container. It's also attached to
# $(COMPOSE_TEST)'s own network so a future test could reach
# seaweedfs/mock-vllm by service name if one ever needs to.
#
# A pip cache volume (installtec-test-pip-cache) is reused across runs so
# repeat invocations mostly skip re-downloading the ~35 dependencies
# (including compiled ones -- cryptography, asyncpg, onnxruntime, numpy).
# MSYS_NO_PATHCONV=1 stops Git Bash from mangling the -v bind-mount paths
# (see docs/deploy-deltas.md's Windows/Git Bash section for the same issue
# elsewhere in this repo).
#
# TESTCONTAINERS_HOST_OVERRIDE=host.docker.internal + --add-host: since
# pytest itself runs inside a container (Docker-outside-of-Docker, see
# above), testcontainers' default "the host to connect to is localhost"
# assumption is wrong here -- "localhost" from inside the pytest
# container is the pytest container, not the machine actually holding the
# sibling Postgres/Redis containers' published ports, so every connection
# attempt got ConnectionRefusedError even though Ryuk (testcontainers'
# reaper) started fine (it uses the Docker socket directly, not a
# published port, so it wasn't affected the same way). The override tells
# testcontainers which hostname to use instead; --add-host makes that
# hostname resolve to the real Docker host even on native Linux Docker
# (host.docker.internal is a Docker Desktop-only builtin otherwise --
# `host-gateway` is the magic value dockerd resolves it to since 20.10).
test-integration: dwg-fixtures
	$(COMPOSE_TEST) up -d
	export MSYS_NO_PATHCONV=1; \
	docker run --rm \
	  --network $(TEST_PROJECT_NAME)_default \
	  --add-host=host.docker.internal:host-gateway \
	  -e TESTCONTAINERS_HOST_OVERRIDE=host.docker.internal \
	  -v "$(CURDIR)/backend:/workspace" \
	  -v "$(CURDIR)/ai-service:/ai-service" \
	  -v /var/run/docker.sock:/var/run/docker.sock \
	  -v installtec-test-pip-cache:/root/.cache/pip \
	  -e REQUIRE_DWG_FIXTURES=$(DWG_REQUIRE) \
	  -w /workspace \
	  python:3.12-slim \
	  bash -c "apt-get update -qq && apt-get install -y -qq --no-install-recommends build-essential >/dev/null && pip install --quiet -e '.[dev]' && python -m pytest tests/integration -q"; \
	STATUS=$$?; \
	$(COMPOSE_TEST) down -v; \
	exit $$STATUS

# tests/api drives the real FastAPI app over ASGI (httpx, no real network
# socket) rather than a real HTTP server, but shares tests/conftest.py's
# postgres_container/redis_container testcontainers fixtures with
# tests/integration, so it needs the same Docker-outside-of-Docker
# container (Docker socket mount, host.docker.internal override) -- see
# test-integration's comment above for why. Mirrors that target exactly,
# just pointed at tests/api.
test-api: dwg-fixtures
	$(COMPOSE_TEST) up -d
	export MSYS_NO_PATHCONV=1; \
	docker run --rm \
	  --network $(TEST_PROJECT_NAME)_default \
	  --add-host=host.docker.internal:host-gateway \
	  -e TESTCONTAINERS_HOST_OVERRIDE=host.docker.internal \
	  -v "$(CURDIR)/backend:/workspace" \
	  -v "$(CURDIR)/ai-service:/ai-service" \
	  -v /var/run/docker.sock:/var/run/docker.sock \
	  -v installtec-test-pip-cache:/root/.cache/pip \
	  -e REQUIRE_DWG_FIXTURES=$(DWG_REQUIRE) \
	  -w /workspace \
	  python:3.12-slim \
	  bash -c "apt-get update -qq && apt-get install -y -qq --no-install-recommends build-essential >/dev/null && pip install --quiet -e '.[dev]' && python -m pytest tests/api -q"; \
	STATUS=$$?; \
	$(COMPOSE_TEST) down -v; \
	exit $$STATUS

# Builds the DWG test fixtures (DXF -> DWG -> DXF, plus recorded corrupt/timeout
# verdicts) with the real ODA converter sandbox; see
# deploy/dwg-converter/build-fixtures.sh. Every test target depends on it and
# passes REQUIRE_DWG_FIXTURES=1 when the .deb is present, so a machine that HAS the
# converter can never silently skip the DWG tests (one without it skips them).
dwg-fixtures:
	REQUIRE_DWG_FIXTURES=$(DWG_REQUIRE) bash deploy/dwg-converter/build-fixtures.sh

test: test-unit test-integration

test-all: test-unit test-integration test-api

build:
	$(COMPOSE) build
