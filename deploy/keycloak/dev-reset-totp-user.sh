#!/usr/bin/env bash
# DEV ONLY. Resets one demo user to a clean, FRESH CONFIGURE_TOTP state
# (permanent password, any existing OTP credential removed) rather than
# clearing required actions the way dev-prep-login-users.sh does for
# users that don't need to prove a step-up flow. Used by
# frontend/e2e/real-backend's Playwright global setup so that spec can
# reliably enrol its own TOTP secret and use it for a real MFA step-up
# (app/security/deps.py::require_mfa_step_up) -- Keycloak never exposes an
# existing credential's secret again after enrolment, so this makes every
# run start from zero rather than trying to reuse one.
#
# Usage (from the repo root, in Git Bash):
#   set -a; . deploy/.env; set +a; bash deploy/keycloak/dev-reset-totp-user.sh <username> <password>
set -euo pipefail
export MSYS_NO_PATHCONV=1

: "${KEYCLOAK_ADMIN:?load deploy/.env first (set -a; . deploy/.env; set +a)}"
: "${KEYCLOAK_ADMIN_PASSWORD:?}"
REALM="${KEYCLOAK_REALM:-installtec}"
KC_CONTAINER="installtec_keycloak"
KCADM="/opt/keycloak/bin/kcadm.sh"
run() { docker exec "$KC_CONTAINER" $KCADM "$@"; }

USERNAME="${1:?usage: $0 <username> <password>}"
PASSWORD="${2:?usage: $0 <username> <password>}"

run config credentials --server http://localhost:8080 --realm master \
    --user "$KEYCLOAK_ADMIN" --password "$KEYCLOAK_ADMIN_PASSWORD" >/dev/null

USER_ID=$(run get users -r "$REALM" -q username="$USERNAME" -q exact=true --fields id --format csv --noquotes | tail -n1 | tr -d '\r')
[ -n "$USER_ID" ] || { echo "User '$USERNAME' not found - run bootstrap.sh first." >&2; exit 1; }

run set-password -r "$REALM" --username "$USERNAME" --new-password "$PASSWORD"

OTP_CREDENTIAL_IDS=$(run get "users/${USER_ID}/credentials" -r "$REALM" --fields id,type --format csv --noquotes \
    | tr -d '\r' | awk -F, '$2 == "otp" { print $1 }')
for cred_id in $OTP_CREDENTIAL_IDS; do
    run delete "users/${USER_ID}/credentials/${cred_id}" -r "$REALM"
done

run update "users/${USER_ID}" -r "$REALM" -s 'requiredActions=["CONFIGURE_TOTP"]'

# Keycloak's brute-force protection (realm-installtec.json's
# bruteForceProtected) tracks failed logins across runs, not just within
# one -- an earlier failed attempt (e.g. a TOTP code that landed right on
# a 30s step boundary) left this counter non-zero even though the
# credential itself was reset above, which then triggered Keycloak's
# "quick login check" penalty (repeated attempts within
# quickLoginCheckMilliSeconds force a ~60s wait, defaults, not overridden
# in the realm import) on the very next real login attempt in a fresh
# test run. Clearing it here, not just the credential, is what actually
# makes every run start clean.
run delete "attack-detection/brute-force/users/${USER_ID}" -r "$REALM" || true

echo "Reset '$USERNAME' to a fresh CONFIGURE_TOTP state (permanent password, no OTP credential, no brute-force history)."
