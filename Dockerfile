# syntax=docker/dockerfile:1.7
# Multi-stage build for APAP_WEB (Fase 1 — esqueleto).
#
# Stage 1 (tailwind-base):
#   - Node 20 on Debian Bookworm slim
#   - Installs Tailwind v4 and compiles the production CSS bundle
#     into /work/app/static/css/output.css.
#
# Stage 2 (builder):
#   - Python 3.11 + build-essential on Debian Bookworm slim
#   - Builds an installable wheel of the project (apap_web)
#   - Inherits the compiled CSS from tailwind-base.
#
# Stage 3 (runtime):
#   - Python 3.11 on Debian Bookworm slim, no Node, no build tools
#   - Non-root user (uid 1001) for the unprivileged process
#   - Installs the wheel produced by the builder
#   - HEALTHCHECK probes /healthz, which is required for CD-02 (issue #1)

ARG PYTHON_VERSION=3.11
ARG NODE_VERSION=20

# ---- Tailwind base --------------------------------------------------------
FROM node:${NODE_VERSION}-bookworm-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0 AS tailwind-base
WORKDIR /work

# Install Tailwind v4 dependencies (separate layer for cache reuse on package.json).
COPY tailwindcss/package.json /work/tailwindcss/
COPY tailwindcss/styles/ /work/tailwindcss/styles/
RUN cd /work/tailwindcss \
    && npm install --no-fund --no-audit

# Compile the production CSS bundle. Templates are copied before the compile
# step so Tailwind can scan them for class usage.
COPY app/templates/ /work/app/templates/
RUN cd /work/tailwindcss \
    && npx tailwindcss -i ./styles/app.css -o /work/app/static/css/output.css --minify

# ---- Builder --------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm@sha256:528257d48c1da0dcecc2e725d1ae34498d60c965f1241e39cd6a85a8859bdf84 AS builder
WORKDIR /work

# Build deps for Python wheels (uvloop, httptools, etc.).
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# Pre-compiled CSS (built in the tailwind-base stage).
COPY --from=tailwind-base /work/app/static/css/output.css /work/app/static/css/output.css

# Build the project wheel.
COPY pyproject.toml README.md /work/
COPY app/ /work/app/
# `docs/setup.md` is the package README (declared in pyproject.toml). The
# `app/templates/` is already in tailwind-base; `docs/` is only needed here
# so `pip wheel` can resolve the README.
COPY docs/ /work/docs/
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /work/dist /work

# ---- Runtime --------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm@sha256:528257d48c1da0dcecc2e725d1ae34498d60c965f1241e39cd6a85a8859bdf84 AS runtime

# Curl is required by the HEALTHCHECK directive.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user with stable UID/GID.
RUN groupadd --system --gid 1001 apap \
    && useradd  --system --uid 1001 --gid apap --create-home apap

WORKDIR /app

# Install the wheel built in the previous stage.
COPY --from=builder /work/dist/*.whl /tmp/wheels/
RUN pip install --no-cache-dir /tmp/wheels/*.whl \
    && rm -rf /tmp/wheels

# Pre-compiled CSS (built in the tailwind-base stage).
COPY --from=builder /work/app/static/css/output.css /app/app/static/css/output.css

USER apap

ENV APAP_INSFORGE_URL=http://localhost:7130 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl --fail --silent http://127.0.0.1:8000/healthz || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
