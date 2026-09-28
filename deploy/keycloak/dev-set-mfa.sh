#!/usr/bin/env bash
# DEV/TEST ONLY. Backs `make dev-mfa-off` / `make dev-mfa-on`: sets
# DEV_DISABLE_MFA in deploy/.env, re-runs bootstrap.sh (which turns login OTP
# off/on in Keycloak) and recreates the backend/worker containers so the
# backend's step-up bypass matches. Usage: dev-set-mfa.sh true|false
set -euo pipefail

VALUE="${1:-}"
case "$VALUE" in true|false) ;; *) echo "usage: $0 true|false" >&2; exit 2 ;; esac

cd "$(dirname "${BASH_SOURCE[0]}")/../.."
ENV_FILE=deploy/.env
[ -f "$ENV_FILE" ] || { echo "$ENV_FILE not found -- run: cp deploy/.env.example $ENV_FILE" >&2; exit 1; }

. deploy/keycloak/lib-env-guard.sh
set -a; . "$ENV_FILE"; set +a
if [ "$VALUE" = "true" ] && ! is_dev_or_test_env; then
    echo "Refusing to disable MFA: APP_ENV='${APP_ENV:-<unset>}' is not exactly 'dev' or 'test'." >&2
    exit 1
fi

# Only this one key is touched; append it if it's missing.
if grep -q '^DEV_DISABLE_MFA=' "$ENV_FILE"; then
    sed -i "s/^DEV_DISABLE_MFA=.*/DEV_DISABLE_MFA=${VALUE}/" "$ENV_FILE"
else
    printf '\nDEV_DISABLE_MFA=%s\n' "$VALUE" >> "$ENV_FILE"
fi
echo "deploy/.env: DEV_DISABLE_MFA=${VALUE}"

set -a; . "$ENV_FILE"; set +a
bash deploy/keycloak/bootstrap.sh

docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.override.dev.yml --env-file "$ENV_FILE" up -d
if [ "$VALUE" = "true" ]; then
    echo "DEV: MFA is now OFF (login OTP + step-up). Run 'make dev-mfa-on' to restore it."
else
    echo "MFA is now ON (login OTP + step-up)."
fi
