# syntax=docker/dockerfile:1.7
# Multi-stage build for the APAP_WEB local backend (Phase 1 of self-host slice).
#
# Stage 1 (builder): install the project wheel via pip wheel.
# Stage 2 (runtime): slim Python + the wheel + a non-root user.
#
# This image runs `app.core.local_backend.app:create_app` which:
# - Reads APAP_LOCAL_BACKEND_DSN (required) and APAP_LOCAL_BACKEND_OAUTH_CONFIGURED (optional)
# - Opens a Postgres connection pool against the DSN at startup
# - Applies the 27-statement DDL (idempotent, ~10 ms overhead)
# - Mounts 4 routers at the documented paths (healthz, rawsql, storage, oauth)
# - Listens on 0.0.0.0:8080
#
# Operator scenario:
#   1. docker build -f docker/local-backend.Dockerfile -t apap-local-backend:1.0.0 .
#   2. docker run --rm -p 8080:8080 \
#        -e APAP_LOCAL_BACKEND_DSN='postgresql://postgres:postgres@apap-pg-test:5432/postgres' \
#        -e APAP_LOCAL_BACKEND_OAUTH_CONFIGURED=false \
#        -e APAP_INITIAL_ADMIN_EMAIL=ardelperal@gmail.com \
#        --network coolify apap-local-backend:1.0.0
#   3. curl http://localhost:8080/healthz -> {"db":"up","storage":"up","oauth":"missing"}

FROM python:3.11-slim-bookworm@sha256:528257d48c1da0dcecc2e725d1ae34498d60c965f1241e39cd6a85a8859bdf84 AS builder

WORKDIR /work

# Build deps for psycopg-binary + cryptography + jwt + the rest of the
# installable wheel. Kept minimal so the wheel stage runs in < 2 min on
# a cold cache.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy only the bits that influence the wheel (keep the build context small).
COPY pyproject.toml README.md ./
COPY app ./app
COPY migration ./migration
COPY tailwindcss ./tailwindcss
# Hatch's metadata validator requires the readme file referenced in
# pyproject.toml ([project] readme = "docs/setup.md"). The local-backend
# doesn't actually use the readme at runtime, but the metadata validator
# errors out without it. COPYing it explicitly is the cheapest fix.
COPY docs ./docs

RUN pip wheel --no-cache-dir --no-deps --wheel-dir /work/dist .

FROM python:3.11-slim-bookworm@sha256:528257d48c1da0dcecc2e725d1ae34498d60c965f1241e39cd6a85a8859bdf84 AS runtime

WORKDIR /app

# Runtime deps: psycopg + httpx + jinja2 + cryptography + itsdangerous
# already pulled by pip install --no-deps at build, so the runtime base
# image only needs the C lib for psycopg.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Non-root user (Coolify respects this when not overridden).
RUN useradd --create-home --shell /bin/bash --uid 1001 app

COPY --from=builder /work/dist/*.whl /tmp/wheels/
RUN pip install --no-cache-dir /tmp/wheels/*.whl \
    && rm -rf /tmp/wheels

# Bundle the small assets the app reads at import time (CSS compiled by
# the web app's Tailwind stage — for the local backend we don't serve
# HTML so we skip the CSS stage). Empty static dir kept for symmetry with
# the web app's expectations.
RUN mkdir -p /app/static /app/templates /app/logs \
    && chown -R app:app /app

USER app

# 8080 is the M0 factory default and matches what the proposed
# Coolify manifest pins in coolify/apap-local-backend.json.
EXPOSE 8080

# /healthz returns 200 with {"db": "up"|"down","storage":"up","oauth":"configured"|"missing"}.
# Healthcheck stops flapping when the lifespan's ensure_schema_and_seed
# finishes (sub-second on a warm cache).
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; r=urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2); d=__import__('json').loads(r.read()); sys.exit(0 if d.get('db') in {'up','down'} and d.get('storage')=='up' else 1)" \
  || exit 1

# `create_app` reads DSN + oauth_configured from env. We pass them via
# env so the CMD stays opaque and the lifespan picks them up at startup.
ENV APAP_LOCAL_BACKEND_DSN="" \
    APAP_LOCAL_BACKEND_OAUTH_CONFIGURED=false \
    PYTHONUNBUFFERED=1

CMD ["uvicorn", "app.core.local_backend.app:create_app_from_env", "--factory", "--host", "0.0.0.0", "--port", "8080"]
