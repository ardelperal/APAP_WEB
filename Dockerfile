# syntax=docker/dockerfile:1.7
# Multi-stage build for APAP_WEB (Fase 1 — esqueleto).
#
# Stage 1 (builder):
#   - Python 3.11 + Node 20 on Debian Bookworm slim
#   - Compiles Tailwind v4 CSS into app/static/css/output.css
#   - Builds an installable wheel of the project (apap_web)
#
# Stage 2 (runtime):
#   - Python 3.11 on Debian Bookworm slim, no Node
#   - Non-root user (uid 1001) for the unprivileged process
#   - Installs the wheel produced by the builder
#   - HEALTHCHECK probes /healthz, which is required for CD-02 (issue #1)

ARG PYTHON_VERSION=3.11
ARG NODE_VERSION=20

# ---- Builder -------------------------------------------------------------
FROM node:${NODE_VERSION}-bookworm-slim AS tailwind-base
WORKDIR /work/tailwind
COPY tailwindcss/package.json ./
RUN npm install --no-fund --no-audit

FROM python:${PYTHON_VERSION}-slim-bookworm AS builder
WORKDIR /work

# Build deps for Python wheels (uvloop, httptools, etc.).
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Node + Tailwind inputs (separate layer for cache reuse).
COPY --from=tailwind-base /work/tailwind/node_modules /work/tailwindcss/node_modules
COPY tailwindcss/package.json tailwindcss/styles/ /work/tailwindcss/
COPY app/templates/ /work/app/templates/

# Compile the production CSS bundle.
RUN cd /work/tailwindcss \
    && npx tailwindcss -i ./styles/app.css -o /work/app/static/css/output.css --minify

# Build the project wheel.
COPY pyproject.toml README.md /work/
COPY app/ /work/app/
COPY tests/ /work/tests/ 2>/dev/null || true
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /work/dist /work

# ---- Runtime -------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

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

# Pre-compiled CSS (built in the builder stage).
COPY --from=builder /work/app/static/css/output.css /app/app/static/css/output.css

USER apap

ENV APAP_INSFORGE_URL=http://localhost:7130 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl --fail --silent http://127.0.0.1:8000/healthz || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
