# syntax=docker/dockerfile:1.7
# Multi-stage build for APAP_WEB (Fase 1 — esqueleto).
#
# Stage 1 (tailwind-base):
#   - Node 20 on Debian Bookworm slim
#   - Installs Tailwind v4 and compiles the production CSS bundle
#     into /work/app/static/css/output.css.
#
# Stage 2 (builder):
#   - Python 3.12.14 + build-essential on Debian Bookworm slim
#   - Builds an installable wheel of the project (apap_web)
#   - Inherits the compiled CSS from tailwind-base.
#
# Stage 3 (runtime):
#   - Python 3.12.14 on Debian Bookworm slim, no Node, no build tools
#   - Non-root user (uid 1001) for the unprivileged process
#   - Installs the wheel produced by the builder
#   - HEALTHCHECK probes /healthz, which is required for CD-02 (issue #1)

ARG PYTHON_VERSION=3.12.14
ARG NODE_VERSION=24
ARG BUILD_SHA=development

# ---- Tailwind base --------------------------------------------------------
# Issue #1043: digest re-pin. node:20-bookworm-slim had frozen at its newest
# (EOL) build carrying fixable CVEs; node:24-bookworm-slim is the current LTS
# line. Digest resolved via the Docker registry API (2026-09-27) and scanned
# clean of fixable Debian CVEs.
FROM node:${NODE_VERSION}-bookworm-slim@sha256:0e0ff40c39bc087845bfb27465a0df4ea419520094bc35842ff83dd8cbe6f9b6 AS tailwind-base
WORKDIR /work

# Install Tailwind v4 dependencies from the committed lockfile.
COPY tailwindcss/package.json tailwindcss/package-lock.json /work/tailwindcss/
COPY tailwindcss/styles/ /work/tailwindcss/styles/
RUN cd /work/tailwindcss \
    && npm ci --no-fund --no-audit

# Compile the production CSS bundle. Templates are copied before the compile
# step so Tailwind can scan them for class usage.
COPY app/templates/ /work/app/templates/
RUN cd /work/tailwindcss \
    && npx tailwindcss -i ./styles/app.css -o /work/app/static/css/output.css --minify

# ---- Builder --------------------------------------------------------------
# Issue #1043: digest re-pin. python:3.12.11-slim-bookworm had frozen on a
# vulnerable Debian build (98 CVEs, run 36339815628); 3.12.14 resolves to a
# rebuilt digest with zero fixable HIGH/CRITICAL CVEs. Digest resolved via
# the Docker registry API (2026-09-27).
FROM python:${PYTHON_VERSION}-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e AS builder
WORKDIR /work

# Build deps for Python wheels (uvloop, httptools, etc.).
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# Pre-compiled CSS (built in the tailwind-base stage).
COPY --from=tailwind-base /work/app/static/css/output.css /work/app/static/css/output.css

# Build the project wheel.
COPY pyproject.toml uv.lock README.md /work/
COPY app/ /work/app/
# `docs/setup.md` is the package README (declared in pyproject.toml). The
# `app/templates/` is already in tailwind-base; `docs/` is only needed here
# so `pip wheel` can resolve the README.
COPY docs/ /work/docs/
RUN pip install --no-cache-dir uv==0.9.28 \
    && uv export --frozen --no-dev --no-emit-project \
        --format requirements-txt --output-file /work/requirements.lock \
    && pip wheel --no-cache-dir --no-deps --wheel-dir /work/dist /work

# ---- Runtime --------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e AS runtime
ARG BUILD_SHA

# Curl is required by the HEALTHCHECK directive.
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user with stable UID/GID.
RUN groupadd --system --gid 1001 apap \
    && useradd  --system --uid 1001 --gid apap --create-home apap

WORKDIR /app

# Install the wheel built in the previous stage.
COPY --from=builder /work/dist/*.whl /tmp/wheels/
COPY --from=builder /work/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock \
    && pip install --no-cache-dir --no-deps /tmp/wheels/*.whl \
    && rm -f /tmp/requirements.lock \
    && rm -rf /tmp/wheels

# Pre-compiled CSS (built in the tailwind-base stage).
COPY --from=builder /work/app/static/css/output.css /app/app/static/css/output.css
# Static assets (M3.2: the magic-link form onsubmit handler lives in
# app/static/js/magic-link-form.js; it must be served over HTTPS so the
# deployed app's strict CSP -- which only allows script-src 'self' -- can
# load it without unsafe-inline or per-request nonces).
COPY --from=builder /work/app/static/js/ /app/app/static/js/

USER apap

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APAP_BUILD_SHA=${BUILD_SHA}

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl --fail --silent http://127.0.0.1:8000/healthz || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
