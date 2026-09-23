#!/usr/bin/env bash
# Idempotently creates the drawings bucket against the SeaweedFS S3 endpoint.
# Run after `docker compose up -d seaweedfs` (or as part of `make up`).
#
# NOTE: deploy/seaweedfs/s3-identities.json ships with a placeholder secret
# key ("S3_SECRET_KEY_PLACEHOLDER"). Before first run, edit that file so its
# secretKey matches S3_SECRET_KEY in deploy/.env (SeaweedFS reads the file
# directly and does not expand env vars itself).
set -euo pipefail

: "${S3_ENDPOINT:=http://localhost:8333}"
: "${S3_ACCESS_KEY:=installtec}"
: "${S3_SECRET_KEY:?S3_SECRET_KEY must be set (must match deploy/seaweedfs/s3-identities.json)}"
: "${S3_BUCKET_DRAWINGS:=installtec-drawings}"
: "${S3_REGION:=us-east-1}"

export AWS_ACCESS_KEY_ID="$S3_ACCESS_KEY"
export AWS_SECRET_ACCESS_KEY="$S3_SECRET_KEY"
export AWS_DEFAULT_REGION="$S3_REGION"

if aws --endpoint-url "$S3_ENDPOINT" s3api head-bucket --bucket "$S3_BUCKET_DRAWINGS" 2>/dev/null; then
    echo "Bucket '$S3_BUCKET_DRAWINGS' already exists."
else
    aws --endpoint-url "$S3_ENDPOINT" s3api create-bucket --bucket "$S3_BUCKET_DRAWINGS"
    echo "Created bucket '$S3_BUCKET_DRAWINGS'."
fi
