#!/usr/bin/env bash
# TEST-ONLY orchestration for the fix/keycloak-step-up freshness proof
# (docs/keycloak-setup.md, docs/build-log.md). Against the real dev stack
# (`make up` already running), this:
#   1. lowers Keycloak's Level 2 ("silver") step-up loa-max-age to ~20s
#      (set-stepup-loa-max-age.sh), instead of the real 300s default,
#   2. recreates the backend container with STEP_UP_MAX_AGE_S=20 to match,
#   3. runs frontend/e2e/real-backend/step-up-freshness.spec.ts, which drives
#      the real login/step-up/approve flow through real Keycloak and asserts
#      how has_recent_step_up (app/security/deps.py) actually behaves,
#   4. ALWAYS restores both back to the real 300s default afterwards
#      (trap, regardless of pass/fail), so a normal `make up`/dev session and
#      the rest of the e2e:real-backend suite are unaffected.
#
# Usage (from the repo root, in Git Bash, with `make up` already running):
#   bash deploy/keycloak/test-stepup-freshness.sh
set -euo pipefail
export MSYS_NO_PATHCONV=1

cd "$(dirname "${BASH_SOURCE[0]}")/../.."  # repo root

test -f deploy/.env || { echo "deploy/.env not found -- run: cp deploy/.env.example deploy/.env" >&2; exit 1; }
set -a; . deploy/.env; set +a

TEST_MAX_AGE_S=20
REAL_MAX_AGE_S=300
COMPOSE="docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.override.dev.yml --env-file deploy/.env"

wait_backend_healthy() {
    echo "Waiting for backend to become healthy..."
    for _ in $(seq 1 60); do
        # local, not global -- restore() below has its OWN "$status" (the
        # script's real exit code) live across this call. Reusing the name
        # without `local` clobbered it with "healthy"/"" here, which then
        # made restore()'s own `exit "$status"` fail with "numeric argument
        # required" (caught live: a real run's trap-triggered restore itself
        # exited 2, masking whatever the actual test outcome had been).
        local health_status
        health_status=$(docker inspect --format='{{.State.Health.Status}}' installtec_backend 2>/dev/null || echo "")
        [ "$health_status" = "healthy" ] && return 0
        sleep 2
    done
    echo "backend never became healthy" >&2
    return 1
}

restore() {
    local status=$?
    echo
    echo "Restoring real settings (loa-max-age=${REAL_MAX_AGE_S}s, STEP_UP_MAX_AGE_S=${REAL_MAX_AGE_S})..."
    bash deploy/keycloak/set-stepup-loa-max-age.sh "$REAL_MAX_AGE_S" || echo "WARNING: failed to restore Keycloak's loa-max-age -- fix by hand before trusting any other step-up test." >&2
    STEP_UP_MAX_AGE_S="$REAL_MAX_AGE_S" $COMPOSE up -d backend
    wait_backend_healthy || echo "WARNING: backend did not report healthy after restore -- check 'docker logs installtec_backend'." >&2
    exit "$status"
}
trap restore EXIT

echo "Lowering Level 2 (silver) step-up's loa-max-age to ${TEST_MAX_AGE_S}s..."
bash deploy/keycloak/set-stepup-loa-max-age.sh "$TEST_MAX_AGE_S"

echo "Recreating backend with STEP_UP_MAX_AGE_S=${TEST_MAX_AGE_S}..."
STEP_UP_MAX_AGE_S="$TEST_MAX_AGE_S" $COMPOSE up -d backend
wait_backend_healthy

echo "Running step-up-freshness.spec.ts..."
( cd frontend && STEP_UP_MAX_AGE_S="$TEST_MAX_AGE_S" npx playwright test --config=playwright.step-up-freshness.config.ts )
