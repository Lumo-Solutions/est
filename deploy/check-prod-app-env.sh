#!/usr/bin/env bash
# Fails if docker-compose.prod.yml doesn't actually pin APP_ENV=production
# and PRODUCTION_MODE=true for every backend-family service, by rendering
# the real merged config (docker compose ... config) and checking it --
# not by grepping the YAML source files, which would pass even if the
# override never actually took effect (wrong service name, a merge that
# didn't override the base's ${APP_ENV:-dev}, etc.).
#
# SERVICES below is the canonical list of backend-family services and must
# be kept in sync BY HAND with docker-compose.prod.yml's x-prod-app-env
# block -- same reasoning as check-identity-grants.sh's own BUCKET_SETTINGS
# comment: a service missing from here entirely is exactly the scenario a
# looser check would silently skip. keycloak/frontend/caddy/postgres/redis/
# seaweedfs are deliberately NOT in this list (see docs/deploy-deltas.md).
#
# Run via `make check-prod-app-env`, or standalone:
#   bash deploy/check-prod-app-env.sh [env_file]
# Needs only a `docker compose config` render -- no containers are started.
set -euo pipefail

ENV_FILE="${1:-deploy/.env}"
DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -f "$ENV_FILE" ]; then
    echo "check-prod-app-env: $ENV_FILE not found" >&2
    exit 1
fi

SERVICES="backend celery-worker celery-worker-vlm celery-worker-email celery-worker-quotation celery-beat"

rendered=$(docker compose -f "$DEPLOY_DIR/docker-compose.yml" -f "$DEPLOY_DIR/docker-compose.prod.yml" --env-file "$ENV_FILE" config)

missing=0
for svc in $SERVICES; do
    # Slice out just this service's own block (from its "  <name>:" line up
    # to the next line back at that same two-space service-level indent) so
    # e.g. checking `backend` can't accidentally match another service's
    # APP_ENV/PRODUCTION_MODE line.
    block=$(echo "$rendered" | awk -v svc="  ${svc}:" '
        $0 == svc { found = 1; print; next }
        found && /^  [a-zA-Z]/ { exit }
        found { print }
    ')
    if [ -z "$block" ]; then
        echo "check-prod-app-env: service '${svc}' not found in the rendered config" >&2
        missing=1
        continue
    fi
    if ! echo "$block" | grep -qE '^\s*APP_ENV: production\s*$'; then
        echo "check-prod-app-env: '${svc}' does not render APP_ENV: production" >&2
        missing=1
    fi
    if ! echo "$block" | grep -qE '^\s*PRODUCTION_MODE: "?true"?\s*$'; then
        echo "check-prod-app-env: '${svc}' does not render PRODUCTION_MODE: true" >&2
        missing=1
    fi
done

if [ "$missing" -ne 0 ]; then
    echo "check-prod-app-env: fix deploy/docker-compose.prod.yml's x-prod-app-env block / per-service environment overrides" >&2
    exit 1
fi
echo "check-prod-app-env: OK -- every backend-family service renders APP_ENV=production, PRODUCTION_MODE=true"
