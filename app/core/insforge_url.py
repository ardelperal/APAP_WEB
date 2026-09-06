"""R7 in the spec: InsForgeClient base URL resolution.

.. deprecated:: 2026-09-06
    The ``APAP_LOCAL_BACKEND=true`` switch this module owns is no
    longer the runtime decision: the Coolify-hosted local backend
    (see ``app.core.local_backend``) is the only supported backend
    as of issue #641 closing the self-host umbrella. The module
    remains so legacy test + dev adapters that still consult it
    can run; production deploys no longer read ``APAP_INSFORGE_URL``
    (the env var is ignored) and always serve traffic from
    ``LocalPostgresExecutor`` via ``app.core.local_backend``.

Lifted out of ``app/core/insforge.py`` so the client module can stay under
the 700-line budget. Reads two environment variables only:

- ``APAP_INSFORGE_URL`` — operator override that wins unconditionally.
- ``APAP_LOCAL_BACKEND`` — truthy (``1|true|yes|on``, case-insensitive)
  flips the default to the loopback FastAPI backend.

Stdlib-only on purpose: this module is imported early in the process
lifecycle (during ``InsForgeClient.__init__``) and must not pull any
project package.
"""

# Deprecated 2026-09-06: this module is no longer the production
# transport. The Coolify-hosted local backend (LocalPostgresExecutor)
# is the only supported backend as of issue #641 closing the
# self-host umbrella. This file remains so the legacy InsForge-
# touching tests can run in CI; production deploys use the
# SqlExecutor-based adapter (a follow-up slice).


from __future__ import annotations

import os
import re

_PRODUCTION_INSFORGE_URL = "https://c3uc9dk6.eu-central.insforge.app"
_LOCAL_URL = "http://localhost:8000"
_LOCAL_TRUTHY = re.compile(r"1|true|yes|on")


def resolve_insforge_url(operator_url: str | None = None) -> str:
    """Return the InsForgeClient base URL per the R7 switch.

    - If ``APAP_INSFORGE_URL`` is non-empty, return it (operator override).
    - Else if ``APAP_LOCAL_BACKEND`` is truthy (``1|true|yes|on``,
      case-insensitive), return ``http://localhost:8000``.
    - Else return the production InsForge URL.
    """
    # ``operator_url`` is reserved for future direct-override callers; the
    # live precedence reads the environment directly.
    del operator_url
    configured = os.environ.get("APAP_INSFORGE_URL", "").strip()
    if configured:
        return configured
    if _LOCAL_TRUTHY.match(os.environ.get("APAP_LOCAL_BACKEND", "").lower()):
        return _LOCAL_URL
    return _PRODUCTION_INSFORGE_URL


__all__ = ["resolve_insforge_url"]
