#!/usr/bin/env bash
# Every AI_* key the shared worker environment (x-backend-env) defines must also be passed to the `backend` service,
# which keeps its own environment list. A key missing from `backend` means the API process silently ignores it
# (found live: AI_PROVIDER=mock reached the workers but not /ai/status). Usage: bash deploy/check-ai-env.sh
set -euo pipefail
f="$(dirname "$0")/docker-compose.yml"
anchor_keys=$(awk '/^x-backend-env:/{on=1;next} on && /^[^ #]/{on=0} on && /^  AI_[A-Z_]+:/{sub(":.*","",$1);print $1}' "$f" | sort -u)
backend_keys=$(awk '/^  backend:/{on=1;next} on && /^  [a-z].*:$/{on=0} on && /^      - AI_[A-Z_]+=/{sub("^      - ","");sub("=.*","");print}' "$f" | sort -u)
missing=$(comm -23 <(echo "$anchor_keys") <(echo "$backend_keys") | tr '\n' ' ')
if [ -n "$missing" ]; then echo "FAIL: AI keys in x-backend-env but not in the backend service: $missing" >&2; exit 1; fi
echo "OK: the backend service passes all $(echo "$anchor_keys" | wc -l | tr -d ' ') AI_* keys the workers get."
