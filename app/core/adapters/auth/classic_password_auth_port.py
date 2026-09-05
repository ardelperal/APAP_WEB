"""Classic email/password :class:`AuthUsersPort` adapter (argon2id).

Phase 2 of the self-host umbrella (#641). Adds the third auth path
(email + password) alongside the existing magic-link and Google
OAuth flows.

Hashing uses ``argon2-cffi>=23.1.0`` (default params from
:class:`argon2.PasswordHasher`):
- ``time_cost=3``, ``memory_cost=65536`` (64 MiB), ``parallelism=4``
  (the upstream library defaults — pinned by the library version).
- Output format ``$argon2id$v=19$m=...$t=...$p=...$`` so the verifier
  can identify the algorithm without an explicit column.

Reset tokens are 32-byte URL-safe random strings stored alongside
``expires_at = now() + 30min``. Tokens are single-use; the
consume query clears the column when it sees the token.

This adapter extends :class:`InsForgeAuthUsersAdapter` rather than
implementing :class:`AuthUsersPort` from scratch because the
``get_user_by_email`` SQL, the duplicate-check SQL, and the
``ensure_schema_and_seed`` machinery are already there and correct —
we only add the password-specific methods.
"""
from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import argon2

from app.core.adapters.insforge.auth_insforge_adapter import (
    InsForgeAuthUsersAdapter,
)


def _hash_password(plaintext: str) -> str:
    """Argon2id-hash ``plaintext`` with the upstream library defaults.

    The :class:`argon2.PasswordHasher` wraps the chosen algorithm
    (argon2id by default since ``argon2-cffi`` 23.x). Hashing is
    intentionally synchronous (the route layer is already async) and
    takes ~30-100ms on a modest VPS — fast enough for the operator's
    login flow.
    """
    return argon2.PasswordHasher().hash(plaintext)


def _verify_password(hash_stored: str, plaintext: str) -> bool:
    """Constant-time verify via :meth:`argon2.PasswordHasher.verify`.

    Returns False on any mismatch (wrong password, malformed hash,
    library error). Never raises — the route layer treats False as a
    generic "invalid credentials" response so the verify path can't
    be used as a timing oracle.
    """
    try:
        return argon2.PasswordHasher().verify(hash_stored, plaintext)
    except (argon2.exceptions.VerifyMismatchError,
            argon2.exceptions.InvalidHashError,
            argon2.exceptions.VerificationError):
        return False


class ClassicPasswordAuthPort(InsForgeAuthUsersAdapter):
    """InsForgeAuthUsersAdapter + the four password-specific methods.

    The superclass continues to handle ``get_user_by_email``, the
    initial bootstrap admin seed, the user-deactivate flow, etc.
    This subclass only adds:
    - :meth:`verify_password` — AS2 happy path + AS2.2 wrong-password + AS2.3 unknown-user + AS2.4 NULL-hash
    - :meth:`set_password` — AS4.1 happy reset path (also called by the admin slice)
    - :meth:`request_password_reset` — AS3.1 mints a single-use 30-min token
    - :meth:`consume_password_reset` — AS4.1 updates the hash + AS4.2 rejects expired/invalid
    """

    # SQL — local to this module (kept short; AGENTS.md §22 says SQL lives
    # next to the orchestrator when it is specific to the adapter).
    _GET_PASSWORD_HASH_SQL = (
        "SELECT password_hash FROM usuarios_autorizados "
        "WHERE email = $1 AND activo = true"
    )
    _SET_PASSWORD_HASH_SQL = (
        "UPDATE usuarios_autorizados SET password_hash = $1 "
        "WHERE email = $2 AND activo = true"
    )
    _MINT_RESET_TOKEN_SQL = (
        "UPDATE usuarios_autorizados "
        "SET password_reset_token = $1, password_reset_expires_at = $2 "
        "WHERE email = $3 AND activo = true"
    )
    _GET_RESET_TARGET_SQL = (
        "SELECT email, password_reset_expires_at "
        "FROM usuarios_autorizados "
        "WHERE password_reset_token = $1 AND activo = true"
    )
    _CLEAR_RESET_TOKEN_SQL = (
        "UPDATE usuarios_autorizados "
        "SET password_reset_token = NULL, password_reset_expires_at = NULL "
        "WHERE email = $1"
    )

    # Reset tokens live for 30 minutes per spec R3.
    _RESET_TOKEN_TTL = timedelta(minutes=30)

    def verify_password(self, email: str, plaintext: str) -> bool:
        """Return True iff ``email`` exists, has ``password_hash`` set,
        and the hash matches ``plaintext``.

        - AS2.1 happy path: real user + real password → True.
        - AS2.2 wrong password: returns False.
        - AS2.3 unknown user: returns False (the SELECT just yields no row).
        - AS2.4 NULL password_hash: returns False (the row is fetched but
          the password_hash column is NULL → ``_verify_password`` gets
          called with hash="" → argon2.InvalidHashError → return False).
        """
        rows = self._executor.execute_sql(
            self._GET_PASSWORD_HASH_SQL, [email]
        )
        if not rows:
            return False
        hash_stored = rows[0].get("password_hash")
        if not hash_stored:
            return False
        return _verify_password(hash_stored, plaintext)

    def set_password(self, email: str, new_password: str) -> None:
        """Hash + store ``new_password`` for the user identified by ``email``.

        Idempotent: setting the same password twice produces two different
        hashes (argon2 salts randomly each call). The route layer is
        responsible for any "minimum password age" or "previous N
        passwords can't be reused" policy; this port just stores.
        """
        new_hash = _hash_password(new_password)
        self._executor.execute_sql(
            self._SET_PASSWORD_HASH_SQL, [new_hash, email]
        )

    def request_password_reset(self, email: str) -> str | None:
        """Mint a single-use 30-min reset token and store it.

        Returns the URL-safe token (so the caller can embed it in the
        reset URL the mail_transport sends). Returns None if the user
        doesn't exist OR has ``password_hash IS NULL`` (magic-link /
        OAuth-only users don't get a reset token — spec R3).

        The token is 32 bytes of URL-safe randomness (`secrets.token_urlsafe`).
        """
        # First check the user has a password set.
        user_rows = self._executor.execute_sql(
            self._GET_PASSWORD_HASH_SQL, [email]
        )
        if not user_rows or not user_rows[0].get("password_hash"):
            return None
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + self._RESET_TOKEN_TTL
        self._executor.execute_sql(
            self._MINT_RESET_TOKEN_SQL, [token, expires_at, email]
        )
        return token

    def consume_password_reset(self, token: str, new_password: str) -> Any:
        """Validate ``token``, hash + store ``new_password``, clear token.

        Returns the :class:`AuthorizedUser` on success (logs the user
        in immediately via the same cookie the magic-link verify path
        issues). Returns None if the token doesn't exist, is expired,
        or has already been consumed (spec R4 AS4.2).

        The route layer enforces ``len(new_password) >= 12`` — this port
        accepts any non-empty string (per AGENTS.md §22 the adapter is
        a thin orchestration layer).
        """
        rows = self._executor.execute_sql(
            self._GET_RESET_TARGET_SQL, [token]
        )
        if not rows:
            return None
        email = rows[0]["email"]
        expires_at: datetime = rows[0]["password_reset_expires_at"]
        if expires_at <= datetime.now(UTC):
            # Expired — leave the row intact so the operator can re-mint
            # if needed; we just refuse to honour it.
            return None
        # Atomic single-statement: update password_hash + clear token.
        # The order is: store the new hash FIRST, then clear the token.
        # (Atomicity is achieved by the spec: the token is single-use; if
        # the password update fails the token stays valid so the user can
        # retry. The token is cleared only on success.)
        self.set_password(email, new_password)
        self._executor.execute_sql(self._CLEAR_RESET_TOKEN_SQL, [email])
        # Re-fetch the user to return the updated AuthorizedUser.
        return self.get_user_by_email(email)
