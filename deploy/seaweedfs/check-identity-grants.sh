#!/usr/bin/env bash
# Fails if any of this platform's S3_BUCKET_* settings lacks a full grant
# (Read/Write/List/Tagging/Admin) in the rendered s3-identities.json.
#
# Guards against exactly the bug Module C1 shipped with: S3_BUCKET_PROCUREMENT
# was added to Settings/.env.example/docker-compose.yml/init-buckets.sh, but
# deploy/seaweedfs/s3-identities.json.template was never updated to grant
# it. init-buckets.sh (SeaweedFS's own admin API, no IAM involved) created
# the bucket fine; every actual object read/write against it then returned
# AccessDenied at runtime, since s3-identities.json is what SigV4 auth
# actually checks. Run via `make render-s3-identities` (and therefore
# `make up`), or standalone as `make check-s3-identities`.
#
# BUCKET_SETTINGS below is the canonical list and must be kept in sync BY
# HAND with everywhere else a bucket setting is wired in:
#   - backend/app/core/config.py's S3_BUCKET_* Settings fields (defaults
#     here must match those defaults)
#   - deploy/.env.example
#   - deploy/docker-compose.yml (x-backend-env + backend's own env list)
#   - deploy/seaweedfs/init-buckets.sh
#   - deploy/seaweedfs/s3-identities.json.template
# Adding a new module's own bucket means touching all six. This script
# intentionally does NOT discover bucket settings by grepping deploy/.env
# for S3_BUCKET_* lines -- a setting missing from .env entirely (using only
# its Settings default) is exactly the scenario a text-discovery approach
# would silently skip checking.
set -euo pipefail

ENV_FILE="${1:-deploy/.env}"
IDENTITIES_FILE="${2:-deploy/seaweedfs/s3-identities.json}"

if [ ! -f "$ENV_FILE" ]; then
    echo "check-identity-grants: $ENV_FILE not found" >&2
    exit 1
fi
if [ ! -f "$IDENTITIES_FILE" ]; then
    echo "check-identity-grants: $IDENTITIES_FILE not found -- run 'make render-s3-identities' first" >&2
    exit 1
fi

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

: "${S3_BUCKET_DRAWINGS:=installtec-drawings}"
: "${S3_BUCKET_PROCUREMENT:=installtec-procurement}"
BUCKET_SETTINGS="S3_BUCKET_DRAWINGS S3_BUCKET_PROCUREMENT"

missing=0
for var_name in $BUCKET_SETTINGS; do
    bucket="${!var_name}"
    for action in Read Write List Tagging Admin; do
        if ! grep -q "\"${action}:${bucket}\"" "$IDENTITIES_FILE"; then
            echo "check-identity-grants: missing '${action}:${bucket}' grant for \$${var_name} in $IDENTITIES_FILE" >&2
            missing=1
        fi
    done
done

if [ "$missing" -ne 0 ]; then
    echo "check-identity-grants: fix deploy/seaweedfs/s3-identities.json.template, then run 'make render-s3-identities'" >&2
    exit 1
fi
echo "check-identity-grants: OK -- every S3_BUCKET_* setting has a full grant in $IDENTITIES_FILE"
