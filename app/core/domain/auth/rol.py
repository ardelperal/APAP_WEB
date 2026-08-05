"""Domain enum for the roles stored in ``usuarios_autorizados``.

Re-exports :class:`app.core.roles.Rol` so the application/port layers
can import the domain enum from a stable path without depending on
``app.core`` (which is the cross-cutting transport concern). The actual
values are owned by :mod:`app.core.roles`; this module exists only to
give the hexagonal slice a dedicated import path (rule 4 — single
source of truth; rule 31 — domain depends on Protocol, not transport).
"""
from app.core.roles import Rol

__all__ = ["Rol"]
