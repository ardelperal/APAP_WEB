"""Local adapter implementing ``ClassicPasswordAuthPort`` (M1, issue #641).

The local backend stores password hashes as argon2id in the
``usuarios_autorizados.password_hash`` column (added in migration
007). The InsForge adapter is the fallback for InsForge deployments
(see ``app/core/adapters/insforge/auth_insforge_adapter.py`` for the
no-op defaults).

Argon2id parameters (RFC 9106, OWASP 2024 recommendation):
- ``time_cost=3`` (~100ms per hash on modern x86)
- ``memory_cost=65536`` (64 MB)
- ``parallelism=4``

These are tunable. They live in the constructor so a deployment can
override them via env vars if a specific server needs different
trade-offs (the recommendation: keep memory_cost constant, raise
time_cost for stronger hashing).
"""
from __future__ import annotations

import argon2
import argon2.exceptions

from app.core.data_access import SqlExecutor
from app.core.domain.auth.user import AuthorizedUser
from app.core.ports.auth_classic_port import ClassicPasswordAuthPort


class ClassicPasswordAuthPortImpl(ClassicPasswordAuthPort):
    """Local-Postgres implementation of classic email/password auth."""

    GET_USER_BY_EMAIL_SQL = """
        SELECT id, email, password_hash, rol, activo
        FROM usuarios_autorizados
        WHERE email = %s
    """

    SET_PASSWORD_SQL = """
        UPDATE usuarios_autorizados
        SET password_hash = %s
        WHERE email = %s
    """

    def __init__(
        self,
        db: SqlExecutor,
        *,
        time_cost: int = 3,
        memory_cost: int = 65536,
        parallelism: int = 4,
    ) -> None:
        self._db = db
        self._hasher = argon2.PasswordHasher(
            time_cost=time_cost,
            memory_cost=memory_cost,
            parallelism=parallelism,
        )

    def verify_password(
        self, email: str, password: str
    ) -> AuthorizedUser | None:
        """Return the user if the password matches; ``None`` otherwise.

        The caller (the login endpoint) must NOT distinguish
        ``None``-from-user-not-found, ``None``-from-no-password-set,
        and ``None``-from-wrong-password. All three yield the same
        generic error to the user to prevent email enumeration.
        """
        rows = self._db.execute_sql(
            self.GET_USER_BY_EMAIL_SQL, [email]
        )
        if not rows:
            return None
        row = rows[0]
        if not row["password_hash"] or not row["activo"]:
            return None
        try:
            self._hasher.verify(row["password_hash"], password)
        except argon2.exceptions.VerifyMismatchError:
            return None
        except argon2.exceptions.InvalidHashError:
            # The stored hash is corrupt (e.g. truncated by a previous
            # migration or a manual edit). Treat as "no password" so
            # the user can re-set it via password reset.
            return None
        return AuthorizedUser.from_row(row)

    def set_password(self, email: str, password: str) -> None:
        """Hash with argon2id and store.

        Idempotent: setting twice replaces the hash. The caller is
        responsible for the surrounding flow (token validation,
        rate limiting, audit log).
        """
        password_hash = self._hasher.hash(password)
        self._db.execute_sql(
            self.SET_PASSWORD_SQL, [password_hash, email]
        )


__all__ = ["ClassicPasswordAuthPortImpl"]
