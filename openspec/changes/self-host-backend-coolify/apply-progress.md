# SDD Apply Progress: self-host-backend-coolify

**Branch**: `feat/self-host-backend-coolify` (to be created from `main`)
**Work units**: M0, M1, M2 (see `tasks.md`)
**Mode**: Strict TDD (orchestrator-confirmed; global maintainer-approved `size:exception`)
**Delivery**: stacked-to-main with maintainer-approved `size:exception`
**Status**: M0 ACCEPTED (69d8e89 docker-compose.yml + gate wiring verified 2026-09-10).

### Cumulative task state

- [x] M0.1.1 Dockerfile multi-stage
- [x] M0.1.2 docker-compose.yml
- [x] M0.1.3 docker-compose build < 300MB  (~239 MB container fs)
- [x] M0.1.4 docker-compose up healthy
- [ ] M0.2.1 app/core/local_backend/__init__.py
- [ ] M0.2.2 db.py (psycopg2 wrapper)
- [ ] M0.2.3 storage.py (boto3 MinIO)
- [ ] M0.2.4 api.py (FastAPI router)
- [ ] M0.2.5 health.py (/healthz)
- [ ] M0.3.1 LocalBackendClient default URL
- [ ] M0.3.2 local_backend router mount
- [ ] M0.3.3 E2E test: local URL
- [ ] M0.3.4 E2E test: app talks to local API
- [ ] M0.4.1 migration/sql/0049_initial_local_backend.sql
- [ ] M0.4.2 bootstrap path
- [ ] M0.4.3 migration idempotent test
- [ ] M0.5.1 web_to_legacy_check_only vs local
- [ ] M0.5.2 E2E legacy_postgres
- [ ] M0.5.3 standalone LocalBackendClient CI mode
- [ ] M1.1.1 0050_add_password_hash.sql
- [ ] M1.1.2 0051_create_magic_link_tokens.sql
- [ ] M1.1.3 apply migrations
- [ ] M1.1.4 idempotency test
- [ ] M1.2.1 auth_classic_port.py
- [ ] M1.2.2 magic_link_port.py
- [ ] M1.3.1 classic_password_auth_port.py (argon2id)
- [ ] M1.3.2 magic_link_port.py
- [ ] M1.3.3 LocalBackend no-op default
- [ ] M1.4.1 POST /api/auth/login
- [ ] M1.4.2 POST /api/auth/logout
- [ ] M1.4.3 POST /api/auth/forgot-password
- [ ] M1.4.4 GET /api/auth/magic
- [ ] M1.4.5 POST /api/auth/reset-password
- [ ] M1.4.6 GET /admin/magic-links
- [ ] M1.5.1 test_classic_password_auth.py
- [ ] M1.5.2 test_magic_link.py
- [ ] M1.5.3 test_local_backend_auth.py
- [ ] M1.6.1 oauth_local_backend_adapter unchanged
- [ ] M1.6.2 password_hash NULL → Google only
- [ ] M1.6.3 password set → both flows
- [ ] M2.1.1 coolify.yaml
- [ ] M2.1.2 coolify deploy
- [ ] M2.1.3 coolify-db verified
- [ ] M2.1.4 coolify-minio provisioned
- [ ] M2.1.5 secrets configured
- [ ] M2.1.6 DNS wildcard
- [ ] M2.2.1 docs/runbooks/self-host-backend.md
- [ ] M2.2.2 deploy procedure
- [ ] M2.2.3 reset password procedure
- [ ] M2.2.4 rotate secret procedure
- [ ] M2.2.5 backup procedure
- [ ] M2.3.1 /healthz from Coolify
- [ ] M2.3.2 TLS active
- [ ] M2.3.3 verify-fallback-ready verde
- [ ] M2.3.4 apap-migrate apply against Coolify
- [ ] M2.3.5 real user smoke test
- [ ] M2.3.6 admin magic-links list
