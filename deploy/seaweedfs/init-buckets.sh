#!/usr/bin/env bash
# Idempotently creates the drawings bucket against the SeaweedFS S3 endpoint.
# Run via `make init-buckets` after `make up`.
#
# deploy/seaweedfs/s3-identities.json is generated from its .template by
# `make render-s3-identities` (also run automatically by `make up`) using
# S3_ACCESS_KEY/S3_SECRET_KEY from deploy/.env -- never hand-edit that file.
set -euo pipefail

: "${S3_ENDPOINT:=http://localhost:8333}"
: "${S3_ACCESS_KEY:=installtec}"
: "${S3_SECRET_KEY:?S3_SECRET_KEY must be set (must match deploy/seaweedfs/s3-identities.json)}"
: "${S3_BUCKET_DRAWINGS:=installtec-drawings}"
: "${S3_BUCKET_PROCUREMENT:=installtec-procurement}"
: "${S3_REGION:=us-east-1}"

export AWS_ACCESS_KEY_ID="$S3_ACCESS_KEY"
export AWS_SECRET_ACCESS_KEY="$S3_SECRET_KEY"
export AWS_DEFAULT_REGION="$S3_REGION"

for bucket in "$S3_BUCKET_DRAWINGS" "$S3_BUCKET_PROCUREMENT"; do
    if aws --endpoint-url "$S3_ENDPOINT" s3api head-bucket --bucket "$bucket" 2>/dev/null; then
        echo "Bucket '$bucket' already exists."
    else
        aws --endpoint-url "$S3_ENDPOINT" s3api create-bucket --bucket "$bucket"
        echo "Created bucket '$bucket'."
    fi
done
