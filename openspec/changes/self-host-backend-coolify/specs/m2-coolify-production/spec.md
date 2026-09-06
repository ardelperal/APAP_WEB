# Spec: M2 — Coolify + producción

This is the M2 milestone of `self-host-backend-coolify`. The deliverable
is a fully provisioned, DNS-routed, TLS-terminated APAP_WEB running in
Coolify, with the verify-fallback-ready gate green and a runbook the
operator can follow to deploy, reset passwords, and rotate secrets.

## Requirement: `coolify.yaml` declares the service

The `coolify.yaml` at the repo root declares the service metadata
that Coolify consumes during provisioning.

### Scenario: Coolify CLI provisions from the file

- GIVEN the operator runs `coolify deploy --from-file coolify.yaml`
- THEN Coolify creates the service `apap-web` with the specified:
  - Image build from local `Dockerfile`
  - Port mapping `8000:8000`
  - Healthcheck
  - Environment variables (with `${...}` placeholders resolved from
    Coolify's secret store)
  - Dependencies on `coolify-db` and `coolify-minio`

## Requirement: TLS via Coolify proxy

- Coolify-proxy terminates TLS at the edge with a Let's Encrypt cert
  (Coolify handles renewal automatically)
- The app serves plain HTTP on the internal port 8000
- The `X-Forwarded-Proto: https` header is honoured by `uvicorn` (via
  `--proxy-headers`)

### Scenario: external HTTPS

- GIVEN the app is running and DNS is configured
- WHEN a user visits `https://apap.example.org/login`
- THEN the request reaches the app over plain HTTP internally
- AND the app's `request.url_for(...)` returns `https://apap.example.org/...`

## Requirement: DNS wildcard

- The operator configures a wildcard DNS record `*.apap.example.org` →
  Coolify-proxy IP
- Coolify-proxy routes by Host header

## Requirement: Secrets are managed via Coolify's secret store

- `APAP_SESSION_SECRET` is a Coolify secret, generated with
  `openssl rand -hex 32` at provisioning time
- `APAP_S3_ACCESS_KEY` and `APAP_S3_SECRET_KEY` are Coolify secrets
  matching the `coolify-minio` deployment
- `APAP_LOCAL_DB_URL` is a Coolify secret derived from `coolify-db`'s
  credentials
- Secrets are rotated via `coolify secrets update apap-web SECRET_NAME=new-value`
  followed by `coolify restart apap-web`
- The app picks up new env vars on restart (no code change required)

## Requirement: Runbook (`docs/runbooks/self-host-backend.md`)

The runbook covers:

1. **Provisioning** (one-time, by the operator):
   - Deploy `coolify-db` if not already deployed
   - Deploy `coolify-minio` (image `minio/minio:latest`, port 9000)
   - Generate `APAP_SESSION_SECRET` with `openssl rand -hex 32`
   - Generate `APAP_S3_ACCESS_KEY` and `APAP_S3_SECRET_KEY`
   - Deploy `apap-web` with `coolify deploy --from-file coolify.yaml`
   - Verify with `curl https://apap.example.org/healthz`

2. **Reset a user's password** (operator-driven):
   - Run `coolify exec apap-web python -c "..."` to generate a magic
     link for the user
   - Deliver the link to the user via the trusted channel
   - User clicks the link, gets logged in, sets a new password

3. **Rotate `APAP_SESSION_SECRET`** (operator-driven, every 90 days):
   - `coolify secrets update apap-web APAP_SESSION_SECRET=$(openssl rand -hex 32)`
   - `coolify restart apap-web`
   - All existing sessions are invalidated (users re-login)
   - Verify with `curl https://apap.example.org/healthz`

4. **Migrate the legacy `.accdb` to the new backend** (one-time):
   - Operator copies the `.accdb` from `local-access/backend/` to a
     secure location
   - Runs `apap-migrate apply --table animal|entrada|voluntario|... \
       --legacy-path /path/to/copy.accdb`
   - The apply runs against `APAP_LOCAL_DB_URL` (since the new backend
     is the default when `APAP_LOCAL_BACKEND=true`)
   - Verifies via `verify-fallback-ready --ci-only` (3/3 green)

5. **Backups** (Coolify cron):
   - Daily: `coolify exec coolify-db pg_dump -U apap apap > /backups/$(date +%F).sql`
   - Daily: `coolify exec coolify-minio mc mirror /data /backups/$(date +%F)`
   - Weekly: ship to offsite (B2, R2, etc.) — out of scope for this epic

## Requirement: The verify-fallback-ready gate is green

- `python -m migration.cli_verify_fallback_ready --ci-only` exits 0
- The 3 CI checks all pass:
  - `tests/migration/test_round_trip.py` green
  - `docs/audits/pii-live-migration-2026-Q3.md` verdict `PASS`
  - `apply --direction web-to-legacy --check-only` exits 0
- A 4th check (the operator-attested signature) can pass after the
  operator runs a real cycle with `apap-migrate apply` and signs the
  report

## Out of scope (M2)

- Migrating real legacy data (the `.accdb` lives at
  `tests/migration/local-access/`; the operator copies and runs
  `apap-migrate apply` manually after M2 lands)
- Offsite backup automation (manual `cron` job is acceptable; the
  migration epic post-M2 handles ongoing backups)
- Multi-tenant provisioning (single tenant for now)
- Email-based magic link delivery (operator-delivery is the MVP)

## Acceptance

- [ ] `coolify deploy --from-file coolify.yaml` creates the service
- [ ] `https://apap.example.org/healthz` returns `{"db": "up", "storage": "up"}`
- [ ] TLS is terminated by Coolify-proxy (Let's Encrypt cert valid)
- [ ] DNS wildcard configured
- [ ] `coolify.yaml` is committed in the repo root
- [ ] Secrets are managed via Coolify's secret store
- [ ] `docs/runbooks/self-host-backend.md` covers provisioning, password
      reset, secret rotation, and backup procedures
- [ ] `verify-fallback-ready --ci-only` exits 0
- [ ] `coolify exec apap-web python -m migration.cli_verify_fallback_ready --ci-only`
      exits 0 from inside the container
- [ ] The operator can run `apap-migrate apply --table animal \
      --legacy-path /path/to/copy.accdb` against the production backend
- [ ] The M2 milestone claim ("fallback ready") can be made once the
      operator-attested check is also green
