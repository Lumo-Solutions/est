.PHONY: up down logs migrate revision seed bootstrap-keycloak dev-token init-buckets test test-unit test-integration lint fmt typecheck build

COMPOSE=docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.override.dev.yml --env-file deploy/.env
COMPOSE_TEST=docker compose -f deploy/docker-compose.test.yml --env-file deploy/.env

up:
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

test-integration:
	$(COMPOSE_TEST) up -d
	cd backend && python -m pytest tests/integration -q; \
	STATUS=$$?; \
	$(COMPOSE_TEST) down -v; \
	exit $$STATUS

test: test-unit test-integration

build:
	$(COMPOSE) build
