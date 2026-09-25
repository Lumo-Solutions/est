.PHONY: up down logs migrate revision seed bootstrap-keycloak dev-token init-buckets render-s3-identities check-s3-identities test test-unit test-integration lint fmt typecheck build

COMPOSE=docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.override.dev.yml --env-file deploy/.env
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

# DEV ONLY -- prints a bearer token for a seeded demo user (default
# estimator1) into .dev-token, e.g. `make dev-token`, or
# `bash deploy/keycloak/dev-token.sh <user> <pass>` directly for a
# different seeded user/role. See that script's header comment.
dev-token:
	set -a; . deploy/.env; set +a; bash deploy/keycloak/dev-token.sh

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

test-unit:
	cd backend && python -m pytest tests/unit -q

# `cd backend && python -m pytest` (the obvious thing to do here) needs a
# host Python matching backend/pyproject.toml's `>=3.12,<3.13` pin, plus
# every `[project.optional-dependencies].dev` package (pytest,
# testcontainers, ...) installed into it. On a fresh Windows dev machine
# neither is guaranteed -- there is no requirement that Python 3.12
# specifically is on PATH, and nothing here ever `pip install`s the dev
# extras into whatever host Python exists. So instead this runs pytest
# inside a throwaway `python:3.12-slim` container: matches the pinned
# interpreter exactly regardless of host setup, and needs nothing besides
# Docker (which is already required for the rest of this Makefile).
#
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
test-integration:
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
	  -w /workspace \
	  python:3.12-slim \
	  bash -c "apt-get update -qq && apt-get install -y -qq --no-install-recommends build-essential >/dev/null && pip install --quiet -e '.[dev]' && python -m pytest tests/integration -q"; \
	STATUS=$$?; \
	$(COMPOSE_TEST) down -v; \
	exit $$STATUS

test: test-unit test-integration

build:
	$(COMPOSE) build
