#!/usr/bin/env bash
# DEV ONLY. Gets a real bearer token for a seeded demo user so you can call the
# API without the browser login flow. It:
#   1. enables the password grant on the installtec-backend client (LOCAL Keycloak only),
#   2. clears the demo user's required actions (TOTP enrolment, temp password),
#   3. gives the user a permanent password,
#   4. requests a token and prints it.
# Never run this against a shared or production Keycloak.
#
# Usage (from the repo root, in Git Bash):
#   set -a; . deploy/.env; set +a; bash deploy/keycloak/dev-token.sh [username] [password]
# Defaults: estimator1 / Estimator1Pass!
set -euo pipefail
export MSYS_NO_PATHCONV=1

: "${KEYCLOAK_ADMIN:?load deploy/.env first (set -a; . deploy/.env; set +a)}"
: "${KEYCLOAK_ADMIN_PASSWORD:?}"
: "${KEYCLOAK_CLIENT_SECRET:?}"
REALM="${KEYCLOAK_REALM:-installtec}"
CLIENT_ID="${KEYCLOAK_CLIENT_ID:-installtec-backend}"
KC_URL="${KEYCLOAK_PUBLIC_URL:-http://localhost:8080}"
USERNAME="${1:-estimator1}"
PASSWORD="${2:-Estimator1Pass!}"
KC_CONTAINER="installtec_keycloak"
KCADM="/opt/keycloak/bin/kcadm.sh"
run() { docker exec "$KC_CONTAINER" $KCADM "$@"; }

run config credentials --server http://localhost:8080 --realm master \
    --user "$KEYCLOAK_ADMIN" --password "$KEYCLOAK_ADMIN_PASSWORD" >/dev/null

CLIENT_UUID=$(run get clients -r "$REALM" -q clientId="$CLIENT_ID" --fields id --format csv --noquotes | tail -n1 | tr -d '\r')
run update "clients/${CLIENT_UUID}" -r "$REALM" -s directAccessGrantsEnabled=true

USER_ID=$(run get users -r "$REALM" -q username="$USERNAME" -q exact=true --fields id --format csv --noquotes | tail -n1 | tr -d '\r')
[ -n "$USER_ID" ] || { echo "User '$USERNAME' not found - run bootstrap.sh first." >&2; exit 1; }
run update "users/${USER_ID}" -r "$REALM" -s 'requiredActions=[]'
run set-password -r "$REALM" --username "$USERNAME" --new-password "$PASSWORD"

RESPONSE=$(curl -s -X POST "${KC_URL}/realms/${REALM}/protocol/openid-connect/token" \
    -d grant_type=password \
    -d client_id="$CLIENT_ID" \
    --data-urlencode client_secret="$KEYCLOAK_CLIENT_SECRET" \
    --data-urlencode username="$USERNAME" \
    --data-urlencode password="$PASSWORD" \
    -d scope=openid)

TOKEN=$(printf '%s' "$RESPONSE" | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')
if [ -z "$TOKEN" ]; then
    echo "Token request failed. Keycloak said:" >&2
    echo "$RESPONSE" >&2
    exit 1
fi

echo "$TOKEN" > .dev-token
echo "Token for '$USERNAME' saved to .dev-token (valid a few minutes; re-run to refresh)."
echo
echo "Try it:"
echo "  curl -s -H \"Authorization: Bearer \$(cat .dev-token)\" http://localhost:8001/api/v1/auth/me"
echo "  curl -s -H \"Authorization: Bearer \$(cat .dev-token)\" http://localhost:8001/api/v1/taxonomy"
