# Build context is the MONOREPO ROOT (see deploy/docker-compose.yml), not
# backend/ -- app/takeoff/prompts.py resolves ai-service/prompts and
# ai-service/schemas relative to the container root at runtime, so those
# directories must ship in the image alongside backend/app. Building with
# backend/ as the context (the SRS's literal `build: ../backend`) silently
# omits them and breaks title-block/scale extraction at runtime; see
# docs/deploy-deltas.md.
FROM python:3.12-slim AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY backend/pyproject.toml ./
COPY backend/app ./app
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir .

FROM python:3.12-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 app
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY backend/app ./app
COPY backend/alembic.ini ./alembic.ini
COPY ai-service/prompts /ai-service/prompts
COPY ai-service/schemas /ai-service/schemas
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1
# --proxy-headers: without it, uvicorn reports scope["scheme"] as "http" for
# every request regardless of what the client actually connected with,
# because the backend<->Caddy hop is plain HTTP inside the compose network
# -- Caddy (deploy/caddy/Caddyfile in prod, Caddyfile.dev in dev) terminates
# the real TLS connection and forwards X-Forwarded-Proto: https. Without
# this flag, request.url_for("auth_callback") (app/api/v1/routes/auth.py)
# builds an http:// redirect_uri even behind HTTPS Caddy, which Keycloak's
# https-only wildcard redirect URI (deploy/keycloak/realm-installtec.json)
# then rejects -- a pre-existing bug (never exercised until Phase 10's dev
# Caddy setup, since dev had no TLS hop before). This container has no
# published host port of its own in prod (deploy/docker-compose.prod.yml
# resets every OTHER internal service's port but never publishes backend's
# either -- only Caddy is reachable from outside), so trusting
# X-Forwarded-* from any peer on this docker network is the same "one
# trusted hop" posture TRUSTED_PROXY_HOPS already assumes for
# X-Forwarded-For (app/core/middleware.py::ClientIpMiddleware).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
