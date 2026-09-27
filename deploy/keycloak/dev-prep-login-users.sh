#!/usr/bin/env bash
# DEV ONLY. Prepares one or more already-seeded demo users (deploy/keycloak/
# bootstrap.sh) for a scripted INTERACTIVE login -- clears CONFIGURE_TOTP/
# UPDATE_PASSWORD required actions and sets a permanent password, same as
# dev-token.sh already does for a single user before its own password-grant
# request. Used by frontend/e2e/real-backend's Playwright global setup so
# those tests can drive the real Keycloak login form without also having to
# automate TOTP enrolment (which docs/keycloak-setup.md documents for a
# human's actual first login instead -- see its "Interactive browser login
# in dev" section for why the two are separate concerns).
#
# Usage (from the repo root, in Git Bash):
#   set -a; . deploy/.env; set +a; bash deploy/keycloak/dev-prep-login-users.sh user1:pass1 [user2:pass2 ...]
set -euo pipefail
export MSYS_NO_PATHCONV=1

: "${KEYCLOAK_ADMIN:?load deploy/.env first (set -a; . deploy/.env; set +a)}"
: "${KEYCLOAK_ADMIN_PASSWORD:?}"
REALM="${KEYCLOAK_REALM:-installtec}"
KC_CONTAINER="installtec_keycloak"
KCADM="/opt/keycloak/bin/kcadm.sh"
run() { docker exec "$KC_CONTAINER" $KCADM "$@"; }

[ "$#" -ge 1 ] || { echo "usage: $0 user1:pass1 [user2:pass2 ...]" >&2; exit 1; }

run config credentials --server http://localhost:8080 --realm master \
    --user "$KEYCLOAK_ADMIN" --password "$KEYCLOAK_ADMIN_PASSWORD" >/dev/null

for pair in "$@"; do
    USERNAME="${pair%%:*}"
    PASSWORD="${pair#*:}"
    USER_ID=$(run get users -r "$REALM" -q username="$USERNAME" -q exact=true --fields id --format csv --noquotes | tail -n1 | tr -d '\r')
    [ -n "$USER_ID" ] || { echo "User '$USERNAME' not found - run bootstrap.sh first." >&2; exit 1; }
    run update "users/${USER_ID}" -r "$REALM" -s 'requiredActions=[]'
    run set-password -r "$REALM" --username "$USERNAME" --new-password "$PASSWORD"
    echo "Prepared '$USERNAME' for interactive login (permanent password, no pending required actions)."
done
