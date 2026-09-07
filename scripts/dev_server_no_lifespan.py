"""Dev server runner with the LocalBackend lifespan disabled.

Used by:
- Local E2E testing (run before `pytest tests/e2e/`).
- CI e2e job in `.github/workflows/ci.yml`.

The lifespan in ``app.main.create_app`` calls ``ensure_schema_and_seed``
and ``ensure_domain_schema`` against LocalBackend. In environments where
LocalBackend is unreachable (CI sandbox, local dev box without a service
key, the e2e-only server we run for Playwright), those calls fail
and the app refuses to start.

This script disables that lifespan with a no-op async context
manager, then starts uvicorn on 127.0.0.1:8000. The HTML routes
(/, /healthz, /unauthorized, /login when Google OAuth creds are set)
and the 302-redirect behavior of /animales etc. all serve correctly.
Data routes that actually need LocalBackend (e.g. /animales listing
animals) will 500 because the real LocalBackend client is not configured
— but the e2e suite does not exercise those.

NOT FOR PRODUCTION. In production, the full lifespan must run so
the bootstrap schema gets created. This script is a developer
ergonomic, nothing more.
"""

from __future__ import annotations

import contextlib

import uvicorn

from app.main import create_app


@contextlib.asynccontextmanager
async def _noop_lifespan(_app):
    """Skip the LocalBackend bootstrap; yield nothing."""
    yield


app = create_app()
app.router.lifespan_context = _noop_lifespan

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
