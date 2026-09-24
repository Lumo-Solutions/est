.PHONY: up down logs migrate revision seed bootstrap-keycloak test test-unit test-integration lint fmt typecheck build

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
init-buckets:
	set -a; . deploy/.env; set +a; bash deploy/seaweedfs/init-buckets.sh

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
