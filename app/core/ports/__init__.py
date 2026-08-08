"""Public port surface for the application's outbound dependencies.

Each port Protocol is the only contract the application layer sees for a
slice of functionality:

- :class:`AuthUsersPort` — read access to ``usuarios_autorizados``
  (the authenticated-user management slice).
- :class:`CatalogosPort` — read access to the catalog (reference-data)
  tables.
- :class:`OAuthPort` — OAuth login flow surface (PKCE minting + code
  exchange against the auth provider).
- :class:`SchemaBootstrapPort` — DDL/seed operations executed by the
  schema-bootstrap flow, with :class:`SqlStatement` as its parameter DTO.

New ports (e.g. ``VolunteersPort``) live alongside these modules under
``app/core/ports/`` and re-export from here.
"""

from __future__ import annotations

from app.core.ports.auth_port import AuthUsersPort
from app.core.ports.catalogos_port import CatalogosPort
from app.core.ports.insforge_error_handler_port import (
    ErrorTranslationPort,
    ErrorUserResponse,
    TranslatableError,
)
from app.core.ports.oauth_port import OAuthPort, OAuthUser
from app.core.ports.schema_bootstrap_port import SchemaBootstrapPort, SqlStatement

__all__ = [
    "AuthUsersPort",
    "CatalogosPort",
    "ErrorTranslationPort",
    "ErrorUserResponse",
    "OAuthPort",
    "OAuthUser",
    "SchemaBootstrapPort",
    "SqlStatement",
    "TranslatableError",
]
