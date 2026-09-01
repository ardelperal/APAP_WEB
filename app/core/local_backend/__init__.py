"""Local backend for APAP_WEB (M0 of self-host-backend-coolify, issue #641).

This package replaces the InsForge BaaS dependency with a FastAPI router
served by the same process, against Postgres (Coolify) and MinIO
(S3-compatible). The public API shape matches the InsForge REST
contract so ``InsForgeClient`` (and the rest of the application) does
not need to know which backend is in use.

Layout:
- ``db.py`` — ``LocalPostgresExecutor``: psycopg2 wrapper that satisfies
  the ``SqlExecutor`` Protocol used by ``InsForgeClient.execute_sql``.
- ``storage.py`` — ``LocalS3Storage``: boto3 wrapper for MinIO. S3 API
  compatibility means boto3 is the standard client.
- ``api.py`` — FastAPI router exposing the three endpoints
  ``InsForgeClient`` consumes (rawsql, storage buckets, oauth flow).
  The router is included in the main app at ``/api`` when
  ``APAP_LOCAL_BACKEND=true``.

M0 of the self-host-backend-coolify openspec.
"""
