# Sourced, not executed. Single source of truth for "is this a dev/test
# environment" -- used to gate anything that seeds known passwords/TOTP
# secrets or weakens a security-relevant Keycloak default, so a single
# mistake (an unset APP_ENV, or a typo like "prod" reaching a real realm)
# fails CLOSED (skip, refuse) rather than open (seed real users with known
# credentials). Deliberately an allow-list (exactly "dev" or "test"), not a
# deny-list of "production" spellings -- an unrecognized value must also
# refuse, not silently proceed.
is_dev_or_test_env() {
    case "${APP_ENV:-}" in
        dev|test) return 0 ;;
        *) return 1 ;;
    esac
}

# The ONLY switch for turning MFA off (login OTP here; the backend applies
# the same rule to step-up, app/core/config.py::mfa_bypass_active): APP_ENV
# exactly dev/test AND DEV_DISABLE_MFA exactly "true". Anything else --
# unset, "True", "1", any other APP_ENV -- is "MFA stays on".
dev_mfa_disabled() {
    is_dev_or_test_env && [ "${DEV_DISABLE_MFA:-}" = "true" ]
}
