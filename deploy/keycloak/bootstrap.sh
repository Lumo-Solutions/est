#!/usr/bin/env bash
# Idempotent post-import setup: sets the confidential client secret from the
# environment (never committed in the realm export), seeds one demo user per
# role in the /tenants/demo group, and prints the JWKS URL.
#
# Run via `make bootstrap-keycloak` after `make up` and after Keycloak has
# finished importing deploy/keycloak/realm-installtec.json.
set -euo pipefail

# Git Bash on Windows rewrites absolute paths like /opt/... into C:/Program Files/Git/opt/...,
# which breaks `docker exec` paths. Harmless on Linux/macOS.
export MSYS_NO_PATHCONV=1

. "$(dirname "${BASH_SOURCE[0]}")/lib-env-guard.sh"

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

# Phase 3 (docs/ui-qa-brief.md): a read-only GET /users endpoint needs the
# backend itself to call Keycloak's admin API (listing users + their realm
# roles for an "add project member"/"users & roles" screen) -- this is a
# SEPARATE credential from the interactive login flow above, so it's
# deliberately least-privilege: only the three read-only realm-management
# client roles it actually needs (view-users/query-users for the user
# list + role mappings, query-groups because tenant scoping is done via
# the caller's /tenants/* group -- see keycloak_admin.py), never
# manage-users, manage-realm, or a realm-admin role.
# serviceAccountsEnabled=true is also set directly here (not left to the
# realm-installtec.json import alone) because a realm that already existed
# before this change won't pick up a JSON edit retroactively -- this
# `update` is what actually flips it on an already-running dev stack.
echo "Enabling installtec-backend's service account (read-only Keycloak admin API access)..."
run update "clients/${CLIENT_UUID}" -r "$REALM" -s serviceAccountsEnabled=true
SERVICE_ACCOUNT_USER_ID=$(run get "clients/${CLIENT_UUID}/service-account-user" -r "$REALM" --fields id --format csv --noquotes | tail -n1 | tr -d '\r')
REALM_MGMT_UUID=$(run get clients -r "$REALM" -q clientId=realm-management --fields id --format csv --noquotes | tail -n1 | tr -d '\r')
grant_client_role_if_missing() {
    local role_name="$1"
    if run get "users/${SERVICE_ACCOUNT_USER_ID}/role-mappings/clients/${REALM_MGMT_UUID}" -r "$REALM" --fields name --format csv --noquotes \
        | tr -d '\r' | grep -qx "$role_name"; then
        echo "  service account already has '${role_name}', skipping."
    else
        run add-roles -r "$REALM" --uid "$SERVICE_ACCOUNT_USER_ID" --cclientid realm-management --rolename "$role_name"
        echo "  granted '${role_name}' to the service account."
    fi
}
grant_client_role_if_missing view-users
grant_client_role_if_missing query-users
grant_client_role_if_missing query-groups

# Keycloak 25+ emits `sub` and `acr` from its built-in 'basic'/'acr' client
# scopes, which are NOT created when the realm import defines its own
# clientScopes (ours does). Without `sub` every bearer token is rejected, so
# make sure the installtec-claims scope carries both mappers. Idempotent.
echo "Ensuring sub/acr mappers on installtec-claims scope..."
SCOPE_ID=$(run get client-scopes -r "$REALM" --fields id,name --format csv --noquotes \
    | tr -d '\r' | grep 'installtec-claims' | tr ',' '\n' | grep -E '^[0-9a-f-]{36}$' | head -n1)
[ -n "$SCOPE_ID" ] || { echo "installtec-claims client scope not found" >&2; exit 1; }
ensure_mapper() {
    local name="$1" type="$2"; shift 2
    if run get "client-scopes/${SCOPE_ID}/protocol-mappers/models" -r "$REALM" --fields name --format csv --noquotes \
        | tr -d '\r' | grep -qx "$name"; then
        echo "  mapper '$name' already present"
    else
        run create "client-scopes/${SCOPE_ID}/protocol-mappers/models" -r "$REALM" \
            -s name="$name" -s protocol=openid-connect -s protocolMapper="$type" "$@"
        echo "  added mapper '$name'"
    fi
}
ensure_mapper sub oidc-sub-mapper \
    -s 'config."access.token.claim"=true' -s 'config."introspection.token.claim"=true'
ensure_mapper acr oidc-acr-mapper \
    -s 'config."access.token.claim"=true' -s 'config."id.token.claim"=true' -s 'config."introspection.token.claim"=true'
# fix/keycloak-step-up: has_recent_step_up (app/security/deps.py) needs the
# standard auth_time claim to tell a genuinely recent step-up from a
# still-valid session/token that just happens to carry acr=silver from long
# ago -- same "not in the built-in scopes we don't have" reason sub/acr
# need their own mappers here.
ensure_mapper auth_time oidc-usersessionmodel-note-mapper \
    -s 'config."user.session.note"=AUTH_TIME' -s 'config."claim.name"=auth_time' -s 'config."jsonType.label"=long' \
    -s 'config."id.token.claim"=true' -s 'config."access.token.claim"=true' -s 'config."userinfo.token.claim"=true'
# Phase 3: same "we don't have the built-in scopes" reason sub/acr/auth_time
# need their own mappers above -- without this, a client_credentials token
# for installtec-backend's own service account (used by
# app/integrations/keycloak_admin.py to call Keycloak's admin API) carries
# NO resource_access.realm-management.roles claim at all, even though the
# role assignment itself is real (visible via
# users/{id}/role-mappings/clients/{realm-management-uuid}) -- Keycloak's
# admin REST API authorizes off the token's own claims, not a fresh DB
# lookup, so every admin API call 403'd until this mapper existed. Harmless
# for every normal human login token: a regular user has zero
# realm-management roles, so this claim is simply empty/absent for them.
ensure_mapper realm-management-roles oidc-usermodel-client-role-mapper \
    -s 'config."usermodel.clientRoleMapping.clientId"=realm-management' \
    -s 'config."multivalued"=true' -s 'config."claim.name"=resource_access.realm-management.roles' \
    -s 'config."jsonType.label"=String' -s 'config."access.token.claim"=true'

# fix/keycloak-step-up: a Level-of-Authentication step-up flow, following
# Keycloak's own documented pattern -- bronze (level 1) = password + TOTP
# at login (SRS: MFA required at first login); silver (level 2) = TOTP
# re-entered recently (a real step-up before a sensitive action, not a
# full re-login: the Cookie authenticator below reattaches the existing
# level-1 session so only the incremental OTP step runs). acr.loa.map on
# the installtec-claims scope (realm-installtec.json) names these levels;
# this is what actually GRANTS them -- an acr.loa.map with no flow behind
# it (the original gap this branch fixes, see docs/build-log.md) never
# lets any real login reach silver at all.
ensure_browser_stepup_flow() {
    if run get authentication/flows -r "$REALM" --fields alias --format csv --noquotes | tr -d '\r' | grep -qx browser-stepup; then
        echo "Authentication flow 'browser-stepup' already exists, skipping."
        return
    fi
    echo "Creating authentication flow 'browser-stepup'..."
    run create authentication/flows -r "$REALM" -s alias=browser-stepup -s providerId=basic-flow -s topLevel=true -s builtIn=false
    # A brand-new flow/subflow resource occasionally isn't visible to the
    # very next call yet (hit live: the first execution-requirement update
    # right after creating the flow 404'd, then succeeded on retry a moment
    # later) -- this is a one-time setup script, so a short, unconditional
    # wait after each creation is simpler and more robust than a retry loop.
    sleep 1

    # kcadm.sh prints "Created new ... with id '...'" to STDERR, not
    # STDOUT (confirmed live: piping stdout alone captured nothing) --
    # 2>&1 is what actually gets it into the pipe these extract the new
    # id from.
    add_exec() { run create "authentication/flows/$1/executions/execution" -r "$REALM" -s provider="$2" 2>&1 \
        | sed -n "s/.*id '\\(.*\\)'.*/\\1/p"; }
    add_subflow() { run create "authentication/flows/$1/executions/flow" -r "$REALM" -s alias="$2" -s type=basic-flow -s description="$3" 2>&1 \
        | sed -n "s/.*id '\\(.*\\)'.*/\\1/p"; sleep 1; }
    set_requirement() { run update "authentication/flows/$1/executions" -r "$REALM" \
        -b "{\"id\":\"$2\",\"requirement\":\"$3\",\"providerId\":\"$4\",\"level\":0,\"index\":$5,\"priority\":$5}"; }

    cookie_id=$(add_exec browser-stepup auth-cookie)
    set_requirement browser-stepup "$cookie_id" ALTERNATIVE auth-cookie 0
    add_subflow browser-stepup "Auth Flow" "Level-of-authentication step-up subflow" >/dev/null
    auth_flow_exec_id=$(run get "authentication/flows/browser-stepup/executions" -r "$REALM" \
        | python3 -c "import json,sys; print(next(e['id'] for e in json.load(sys.stdin) if e['displayName']=='Auth Flow'))")
    run update "authentication/flows/browser-stepup/executions" -r "$REALM" \
        -b "{\"id\":\"${auth_flow_exec_id}\",\"requirement\":\"ALTERNATIVE\"}"

    add_subflow "Auth%20Flow" "Level 1" "bronze: password + TOTP at login" >/dev/null
    add_subflow "Auth%20Flow" "Level 2" "silver: TOTP re-entered recently (step-up)" >/dev/null
    level1_id=$(run get "authentication/flows/Auth%20Flow/executions" -r "$REALM" \
        | python3 -c "import json,sys; print(next(e['id'] for e in json.load(sys.stdin) if e['displayName']=='Level 1'))")
    level2_id=$(run get "authentication/flows/Auth%20Flow/executions" -r "$REALM" \
        | python3 -c "import json,sys; print(next(e['id'] for e in json.load(sys.stdin) if e['displayName']=='Level 2'))")
    run update "authentication/flows/Auth%20Flow/executions" -r "$REALM" -b "{\"id\":\"${level1_id}\",\"requirement\":\"CONDITIONAL\"}"
    run update "authentication/flows/Auth%20Flow/executions" -r "$REALM" -b "{\"id\":\"${level2_id}\",\"requirement\":\"CONDITIONAL\"}"

    cond1_id=$(add_exec "Level%201" conditional-level-of-authentication)
    set_requirement "Level%201" "$cond1_id" REQUIRED conditional-level-of-authentication 0
    run create "authentication/executions/${cond1_id}/config" -r "$REALM" -s alias=level1-condition \
        -s 'config."loa-condition-level"=1' -s 'config."loa-max-age"=28800'
    add_exec "Level%201" auth-username-password-form >/dev/null
    otp1_id=$(add_exec "Level%201" auth-otp-form)
    set_requirement "Level%201" "$otp1_id" REQUIRED auth-otp-form 2

    cond2_id=$(add_exec "Level%202" conditional-level-of-authentication)
    set_requirement "Level%202" "$cond2_id" REQUIRED conditional-level-of-authentication 0
    run create "authentication/executions/${cond2_id}/config" -r "$REALM" -s alias=level2-condition \
        -s 'config."loa-condition-level"=2' -s 'config."loa-max-age"=300'
    otp2_id=$(add_exec "Level%202" auth-otp-form)
    set_requirement "Level%202" "$otp2_id" REQUIRED auth-otp-form 1

    echo "  'browser-stepup' created."
}
ensure_browser_stepup_flow
echo "Binding 'browser-stepup' as the realm's browser flow..."
run update "realms/${REALM}" -s browserFlow=browser-stepup

# dev-token.sh (scripted bearer-token access) must stay bronze-only, no
# matter that its demo users now have a real OTP credential seeded below
# for interactive login -- Keycloak's built-in "direct grant" flow has its
# own "Direct Grant - Conditional OTP" subflow that activates SPECIFICALLY
# BECAUSE a user has one configured, which would otherwise make every
# direct-grant request fail with invalid_grant unless it also sent an otp
# param. Disabling it is what actually keeps direct grant simple/bronze.
#
# This is a realm-wide weakening of the direct grant flow (anyone using
# password grant against ANY user skips OTP even if that user has a real
# credential), so it's gated by the exact same dev/test-only guard as the
# demo users/secrets below, not applied unconditionally -- outside dev/test
# the direct grant flow's OTP step is left exactly as Keycloak's own
# built-in default has it, and dev-token.sh (which relies on this being
# disabled) is dev/test-only, documented in its own header comment.
if is_dev_or_test_env; then
    echo "Disabling direct grant's conditional OTP (dev-token.sh stays bronze-only, APP_ENV=${APP_ENV})..."
    DIRECT_GRANT_OTP_ID=$(run get "authentication/flows/direct%20grant/executions" -r "$REALM" --fields id,displayName --format csv --noquotes \
        | tr -d '\r' | awk -F, '$2=="Direct Grant - Conditional OTP"{print $1}')
    [ -n "$DIRECT_GRANT_OTP_ID" ] && run update "authentication/flows/direct%20grant/executions" -r "$REALM" \
        -b "{\"id\":\"${DIRECT_GRANT_OTP_ID}\",\"requirement\":\"DISABLED\"}"
else
    echo "APP_ENV='${APP_ENV:-<unset>}' is not 'dev' or 'test' -- leaving direct grant's Conditional OTP as Keycloak's own default (dev-token.sh only works in dev/test)."
fi

# Closes the gap where a user could remove their only OTP credential via
# Keycloak's own account console, which -- since account-console isn't
# something this app ever links to (it has its own frontend) -- has no
# legitimate use here and is pure attack surface against step-up. Disabling
# the client makes /realms/{realm}/account/ 404 outright rather than
# relying on self-service delete-protection semantics.
echo "Disabling the built-in account/account-console clients..."
for client_id in account account-console; do
    uuid=$(run get clients -r "$REALM" -q clientId="$client_id" --fields id --format csv --noquotes | tail -n1 | tr -d '\r')
    [ -n "$uuid" ] && run update "clients/${uuid}" -r "$REALM" -s enabled=false
done

seed_user() {
    local username="$1" role="$2" password="$3"
    if run get users -r "$REALM" -q username="$username" --fields id --format csv --noquotes | grep -q .; then
        echo "User '$username' already exists, skipping creation."
    else
        echo "Creating user '$username' (role: $role)..."
        run create users -r "$REALM" -s username="$username" -s enabled=true \
            -s emailVerified=true -s email="${username}@demo.installtec.local" \
            -s 'groups=["/tenants/demo"]'
        run set-password -r "$REALM" --username "$username" --new-password "$password"
        run add-roles -r "$REALM" --uusername "$username" --rolename "$role"
    fi
}

# DEV/TEST ONLY -- fixed TOTP secrets so both a human (any authenticator
# app, enter the base32 form manually) and frontend/e2e/real-backend's
# Playwright specs (via otplib, computing codes from the SAME secret) can
# log in deterministically. The realm's own bronze level now REQUIRES a
# working OTP credential to log in at all (auth-otp-form is REQUIRED, not
# conditional -- see ensure_browser_stepup_flow above), so a demo user with
# no credential and no CONFIGURE_TOTP required action left pending would
# otherwise be unable to log in at all. A developer who wants to test
# genuine QR-code enrolment instead runs
# deploy/keycloak/dev-reset-totp-user.sh <user> <pass> first, which clears
# this seeded credential and puts CONFIGURE_TOTP back.
seed_totp() {
    local username="$1" raw_secret="$2"
    local user_id
    user_id=$(run get users -r "$REALM" -q username="$username" --fields id --format csv --noquotes | tail -n1 | tr -d '\r')
    # Always, regardless of the branch below: a leftover CONFIGURE_TOTP
    # required action (e.g. from dev-reset-totp-user.sh, or from this
    # script's own OLDER behaviour before dev-fixed secrets existed) forces
    # enrolment on next login even once a credential exists, since
    # seed_user() above only clears requiredActions for a BRAND NEW user,
    # not one that "already exists, skipping creation" -- found live: a
    # user with a valid seeded OTP credential still got shown the QR-code
    # enrolment page because of this exact leftover flag.
    run update "users/${user_id}" -r "$REALM" -s 'requiredActions=[]'
    if run get "users/${user_id}/credentials" -r "$REALM" --fields type --format csv --noquotes | tr -d '\r' | grep -qx otp; then
        echo "  '$username' already has an OTP credential, skipping."
        return
    fi
    run update "users/${user_id}" -r "$REALM" -s "credentials=[{\"type\":\"otp\",\"userLabel\":\"dev-fixed\",\"secretData\":\"{\\\"value\\\":\\\"${raw_secret}\\\"}\",\"credentialData\":\"{\\\"subType\\\":\\\"totp\\\",\\\"digits\\\":6,\\\"period\\\":30,\\\"algorithm\\\":\\\"HmacSHA1\\\"}\"}]"
    local b32
    b32=$(python3 -c "import base64; print(base64.b32encode('${raw_secret}'.encode()).decode())")
    echo "  '$username' TOTP secret (base32, for a real authenticator app or otplib): ${b32}"
}

# Fail CLOSED, not open: demo users get KNOWN passwords and (below)
# dev-fixed TOTP secrets, which must never be seeded anywhere but a real
# dev/test environment -- an unset APP_ENV, or any value other than
# exactly "dev"/"test" (including "prod", "production", or a typo/unknown
# value), skips this whole block rather than defaulting to "seed anyway".
# See lib-env-guard.sh and test-lib-env-guard.sh.
if is_dev_or_test_env; then
    seed_user estimator1 estimator "Estimator1Pass!"
    seed_user lead1 lead_estimator "Lead1Pass!"
    seed_user procurement1 procurement_head "Procurement1Pass!"
    seed_user bd1 bd_director "Bd1Pass!"
    seed_user md1 managing_director "Md1Pass!"

    echo "Seeding dev-fixed TOTP secrets (APP_ENV=${APP_ENV})..."
    seed_totp estimator1 "installtec-dev-estimator1-totp01"
    seed_totp lead1 "installtec-dev-lead1-totp01-secret"
    seed_totp procurement1 "installtec-dev-procurement1-totp1"
    seed_totp bd1 "installtec-dev-bd1-totp-secret1"
    seed_totp md1 "installtec-dev-md1-totp-secret01"

    echo
    echo "Demo users seeded (permanent passwords, dev-fixed TOTP already enrolled -- see docs/keycloak-setup.md)."
else
    echo
    echo "APP_ENV='${APP_ENV:-<unset>}' is not exactly 'dev' or 'test' -- refusing to create demo users with known passwords or dev-fixed TOTP secrets. This script's user/credential seeding is for local development and automated tests only; set APP_ENV=dev (or test) to run it, or enrol real users by hand for any other environment." >&2
fi

echo "JWKS URL: ${KEYCLOAK_PUBLIC_URL:-http://localhost:8080}/realms/${REALM}/protocol/openid-connect/certs"
