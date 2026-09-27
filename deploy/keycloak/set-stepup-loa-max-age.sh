#!/usr/bin/env bash
# TEST-ONLY. Changes the realm's Level 2 ("silver" step-up) authenticator
# config's loa-max-age -- deploy/keycloak/bootstrap.sh's
# ensure_browser_stepup_flow sets this to 300s (level2-condition) when it
# FIRST creates the browser-stepup flow, and never touches it again once the
# flow exists ("already exists, skipping"), so it has to be changed live via
# kcadm for deploy/keycloak/test-stepup-freshness.sh to prove
# has_recent_step_up's real-Keycloak behaviour on a short (~20s) window
# instead of waiting out a real 300s for every assertion.
#
# Usage (from the repo root, in Git Bash):
#   set -a; . deploy/.env; set +a; bash deploy/keycloak/set-stepup-loa-max-age.sh <seconds>
set -euo pipefail
export MSYS_NO_PATHCONV=1

: "${KEYCLOAK_ADMIN:?load deploy/.env first (set -a; . deploy/.env; set +a)}"
: "${KEYCLOAK_ADMIN_PASSWORD:?}"
REALM="${KEYCLOAK_REALM:-installtec}"
SECONDS_VALUE="${1:?Usage: set-stepup-loa-max-age.sh <seconds>}"
KC_CONTAINER="installtec_keycloak"
KCADM="/opt/keycloak/bin/kcadm.sh"
run() { docker exec "$KC_CONTAINER" $KCADM "$@"; }

run config credentials --server http://localhost:8080 --realm master \
    --user "$KEYCLOAK_ADMIN" --password "$KEYCLOAK_ADMIN_PASSWORD" >/dev/null

# authenticationConfig on the execution is the config resource's id (a UUID),
# not its alias ("level2-condition") -- same reason bootstrap.sh's own
# add_exec/add_subflow helpers parse ids out of kcadm's create output rather
# than guessing them, and the same python3-json approach it already uses to
# pick one execution out of a flow's list by displayName/providerId.
CONFIG_ID=$(run get "authentication/flows/Level%202/executions" -r "$REALM" \
    | python3 -c "import json,sys; e=next(e for e in json.load(sys.stdin) if e['providerId']=='conditional-level-of-authentication'); print(e['authenticationConfig'])")
[ -n "$CONFIG_ID" ] && [ "$CONFIG_ID" != "None" ] || { echo "level2-condition authenticatorConfig not found -- has bootstrap.sh's ensure_browser_stepup_flow run?" >&2; exit 1; }

# kcadm update with only -s flags GETs the existing representation, merges
# the given dot-path keys in, and PUTs it back -- config."loa-condition-level"
# is left exactly as it already is.
run update "authentication/config/${CONFIG_ID}" -r "$REALM" -s "config.\"loa-max-age\"=${SECONDS_VALUE}"
echo "Level 2 (silver) step-up's loa-max-age set to ${SECONDS_VALUE}s."
