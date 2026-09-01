"""Protocol for classic email/password authentication (M1, issue #641).

This is the application-side contract. The local adapter
(``ClassicPasswordAuthPort``) implements it against Postgres; the
InsForge adapter falls back to ``NotImplementedError`` for
``set_password`` (InsForge has no password store) and ``None`` for
``verify_password`` (the user has no password set, log in with Google).
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.core.domain.auth.user import AuthorizedUser


@runtime_checkable
class ClassicPasswordAuthPort(Protocol):
    """Backend-agnostic surface for email/password login."""

    def verify_password(
        self, email: str, password: str
    ) -> AuthorizedUser | None:
        """Return the user if the password matches, else ``None``.

        ``None`` covers three distinct cases that the caller must NOT
        distinguish to the outside world: user not found, user has
        no password set (OAuth-only), wrong password. Splitting them
        is an email-enumeration / timing oracle.
        """
        ...

    def set_password(self, email: str, password: str) -> None:
        """Hash ``password`` with argon2id and store it on the user.

        Idempotent: calling twice replaces the hash. The caller is
        responsible for the surrounding flow (token validation, rate
        limiting, etc.) — this method just writes the hash.
        """
        ...


__all__ = ["ClassicPasswordAuthPort"]
