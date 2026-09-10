# syntax=docker/dockerfile:1.7
# Multi-stage build for APAP_WEB (Fase 1 — esqueleto).
#
# Stage 1 (tailwind-base):
#   - Node 20 on Debian Bookworm slim
#   - Installs Tailwind v4 and compiles the production CSS bundle
#     into /work/app/static/css/output.css.
#
# Stage 2 (builder):
#   - Python 3.12.11 + build-essential on Debian Bookworm slim
#   - Builds an installable wheel of the project (apap_web)
#   - Inherits the compiled CSS from tailwind-base.
#
# Stage 3 (runtime):
#   - Python 3.12.11 on Debian Bookworm slim, no Node, no build tools
#   - Non-root user (uid 1001) for the unprivileged process
#   - Installs the wheel produced by the builder
#   - HEALTHCHECK probes /healthz, which is required for CD-02 (issue #1)

ARG PYTHON_VERSION=3.12.11
ARG NODE_VERSION=20
ARG BUILD_SHA=development

# ---- Tailwind base --------------------------------------------------------
FROM node:${NODE_VERSION}-bookworm-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0 AS tailwind-base
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
FROM python:${PYTHON_VERSION}-slim-bookworm@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7 AS builder
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
FROM python:${PYTHON_VERSION}-slim-bookworm@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7 AS runtime
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
