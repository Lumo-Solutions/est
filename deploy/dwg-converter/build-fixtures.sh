#!/usr/bin/env bash
# Builds backend/tests/fixtures/dwg/ with the real ODA converter (see
# backend/tests/fixtures/build_dwg_fixtures.py). Run via `make dwg-fixtures`.
#
# Starts the SAME hardened sandbox the app uses (no network, read-only root,
# tmpfs, no caps, limits) on a throw-away spool volume, runs the builder in a
# python container that shares that volume, then removes both.
#
# No .deb (deploy/vendor/oda/ is gitignored and not on every machine)? Then no
# fixtures can be built: this exits 0 with a loud message, and the DWG tests
# skip -- unless REQUIRE_DWG_FIXTURES=1 (set by make test-*), where they fail.
set -euo pipefail
export MSYS_NO_PATHCONV=1

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && { pwd -W 2>/dev/null || pwd; })"
VOL=installtec-dwgfix-spool
NAME=installtec-dwgfix-converter
IMAGE=installtec-dwg-converter:dev

if ! ls "$ROOT"/deploy/vendor/oda/ODAFileConverter*.deb >/dev/null 2>&1; then
    echo "dwg-fixtures: no ODA .deb in deploy/vendor/oda/ -- DWG fixtures NOT built." >&2
    [ "${REQUIRE_DWG_FIXTURES:-0}" = "1" ] && exit 1
    exit 0
fi

docker buildx build --quiet --build-context oda="$ROOT/deploy/vendor/oda" -t "$IMAGE" --load "$ROOT/deploy/dwg-converter" >/dev/null

cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; docker volume rm -f "$VOL" >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup
docker volume create "$VOL" >/dev/null
docker run -d --name "$NAME" --network none --read-only --tmpfs /tmp:size=1g,mode=1777 \
    --cap-drop ALL --security-opt no-new-privileges --memory 2g --cpus 1.5 --pids-limit 256 \
    -u 1000:1000 -v "$VOL":/spool "$IMAGE" >/dev/null

docker run --rm \
    -e DWG_SPOOL_DIR=/spool -v "$VOL":/spool \
    -v "$ROOT/backend:/workspace" -v "$ROOT/ai-service:/ai-service" \
    -v installtec-test-pip-cache:/root/.cache/pip -w /workspace \
    python:3.12-slim \
    bash -c "umask 000 && pip install --quiet -e '.[dev]' && python -m tests.fixtures.build_dwg_fixtures"
