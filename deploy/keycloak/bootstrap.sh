#!/usr/bin/env bash
# Idempotent post-import setup: sets the confidential client secret from the
# environment (never committed in the realm export), seeds one demo user per
# role in the /tenants/demo group, and prints the JWKS URL.
#
# Run via `make bootstrap-keycloak` after `make up` and after Keycloak has
# finished importing deploy/keycloak/realm-installtec.json.
set -euo pipefail

: "${KEYCLOAK_ADMIN:?KEYCLOAK_ADMIN must be set (see deploy/.env)}"
: "${KEYCLOAK_ADMIN_PASSWORD:?KEYCLOAK_ADMIN_PASSWORD must be set}"
: "${KEYCLOAK_CLIENT_SECRET:?KEYCLOAK_CLIENT_SECRET must be set}"
REALM="${KEYCLOAK_REALM:-installtec}"
KC_CONTAINER="installtec_keycloak"
KCADM="/opt/keycloak/bin/kcadm.sh"

run() { docker exec "$KC_CONTAINER" $KCADM "$@"; }

echo "Logging in to Keycloak admin CLI..."
run config credentials --server http://localhost:8080 --realm master \
    --user "$KEYCLOAK_ADMIN" --password "$KEYCLOAK_ADMIN_PASSWORD"

echo "Setting installtec-backend client secret..."
CLIENT_UUID=$(run get clients -r "$REALM" -q clientId=installtec-backend --fields id --format csv --noquotes | tail -n1)
run update "clients/${CLIENT_UUID}" -r "$REALM" -s "secret=${KEYCLOAK_CLIENT_SECRET}"

seed_user() {
    local username="$1" role="$2" password="$3"
    if run get users -r "$REALM" -q username="$username" --fields id --format csv --noquotes | grep -q .; then
        echo "User '$username' already exists, skipping creation."
    else
        echo "Creating user '$username' (role: $role)..."
        run create users -r "$REALM" -s username="$username" -s enabled=true \
            -s emailVerified=true -s email="${username}@demo.installtec.local" \
            -s 'requiredActions=["CONFIGURE_TOTP"]' \
            -s 'groups=["/tenants/demo"]'
        USER_ID=$(run get users -r "$REALM" -q username="$username" --fields id --format csv --noquotes | tail -n1)
        run set-password -r "$REALM" --username "$username" --new-password "$password" --temporary
        run add-roles -r "$REALM" --uusername "$username" --rolename "$role"
    fi
}

seed_user estimator1 estimator "Estimator1Pass!"
seed_user lead1 lead_estimator "Lead1Pass!"
seed_user procurement1 procurement_head "Procurement1Pass!"
seed_user bd1 bd_director "Bd1Pass!"
seed_user md1 managing_director "Md1Pass!"

echo
echo "Demo users seeded (temporary passwords, TOTP enrolment required on first login)."
echo "JWKS URL: ${KEYCLOAK_PUBLIC_URL:-http://localhost:8080}/realms/${REALM}/protocol/openid-connect/certs"
