"""Authorization role definitions with no application-layer dependencies."""

from enum import StrEnum


class Rol(StrEnum):
    """Roles supported by ``usuarios_autorizados``."""

    DEVELOPER = "developer"
    ADMIN = "admin"
    KEY_USER = "key_user"
    READER = "reader"
