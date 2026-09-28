#!/usr/bin/env bash
# Standalone check for lib-env-guard.sh's is_dev_or_test_env -- run directly
# (`bash deploy/keycloak/test-lib-env-guard.sh`) or from CI. No Docker/Keycloak
# needed; this only exercises the shell logic that decides whether
# bootstrap.sh is allowed to seed known passwords/TOTP secrets or weaken the
# direct grant flow.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
. ./lib-env-guard.sh

failures=0

assert_true() {
    local label="$1"
    if ! is_dev_or_test_env; then
        echo "FAIL: $label -- expected is_dev_or_test_env to succeed (APP_ENV='${APP_ENV:-<unset>}')" >&2
        failures=$((failures + 1))
    else
        echo "ok: $label"
    fi
}

assert_false() {
    local label="$1"
    if is_dev_or_test_env; then
        echo "FAIL: $label -- expected is_dev_or_test_env to fail (APP_ENV='${APP_ENV:-<unset>}')" >&2
        failures=$((failures + 1))
    else
        echo "ok: $label"
    fi
}

unset APP_ENV
assert_false "unset APP_ENV"

APP_ENV=""
assert_false "empty APP_ENV"

APP_ENV="dev"
assert_true "APP_ENV=dev"

APP_ENV="test"
assert_true "APP_ENV=test"

APP_ENV="prod"
assert_false "APP_ENV=prod"

APP_ENV="production"
assert_false "APP_ENV=production"

APP_ENV="staging"
assert_false "APP_ENV=staging (unrecognized value must also refuse)"

APP_ENV="Dev"
assert_false "APP_ENV=Dev (case-sensitive: only exact 'dev'/'test')"

# dev_mfa_disabled: MFA is off only for APP_ENV exactly dev/test AND
# DEV_DISABLE_MFA exactly "true" -- everything else fails closed (MFA on).
assert_mfa() {
    local label="$1" expected="$2" actual=off
    dev_mfa_disabled && actual=disabled || actual=on
    if [ "$actual" != "$expected" ]; then
        echo "FAIL: $label -- expected MFA $expected, got $actual (APP_ENV='${APP_ENV:-<unset>}', DEV_DISABLE_MFA='${DEV_DISABLE_MFA:-<unset>}')" >&2
        failures=$((failures + 1))
    else
        echo "ok: $label"
    fi
}

unset APP_ENV DEV_DISABLE_MFA
assert_mfa "both unset" on
APP_ENV=dev; assert_mfa "dev, flag unset" on
DEV_DISABLE_MFA=false; assert_mfa "dev, flag false" on
DEV_DISABLE_MFA=true; assert_mfa "dev, flag true" disabled
APP_ENV=test; assert_mfa "test, flag true" disabled
DEV_DISABLE_MFA=True; assert_mfa "test, flag 'True' (exact 'true' only)" on
DEV_DISABLE_MFA=1; assert_mfa "test, flag '1'" on
DEV_DISABLE_MFA=true
APP_ENV=production; assert_mfa "production, flag true" on
APP_ENV=prod; assert_mfa "prod, flag true" on
APP_ENV=staging; assert_mfa "staging, flag true" on
APP_ENV=""; assert_mfa "empty APP_ENV, flag true" on
unset APP_ENV; assert_mfa "unset APP_ENV, flag true" on

if [ "$failures" -gt 0 ]; then
    echo "$failures check(s) failed" >&2
    exit 1
fi
echo "All env-guard checks passed."
