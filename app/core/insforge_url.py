"""R7 in the spec: InsForgeClient base URL resolution.

Lifted out of ``app/core/insforge.py`` so the client module can stay under
the 700-line budget. Reads two environment variables only:

- ``APAP_INSFORGE_URL`` — operator override that wins unconditionally.
- ``APAP_LOCAL_BACKEND`` — truthy (``1|true|yes|on``, case-insensitive)
  flips the default to the loopback FastAPI backend.

Stdlib-only on purpose: this module is imported early in the process
lifecycle (during ``InsForgeClient.__init__``) and must not pull any
project package.
"""

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
