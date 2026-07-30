"""Negative fixture: proper annotation on auth dep params — must NOT be flagged."""

from fastapi import Depends

from app.core.auth_dependencies import (
    AuthenticatedUser,
    require_authorized_user,
    require_developer_user,
    require_writer_user,
)


def handler_with_typed_user_authorized(
    user: AuthenticatedUser = Depends(require_authorized_user),
) -> dict:
    if isinstance(user, dict):
        return {"ok": True}
    return user


def handler_with_typed_user_writer(
    data: str,
    user: AuthenticatedUser = Depends(require_writer_user),
) -> dict:
    if isinstance(user, dict):
        return {"ok": True, "data": data}
    return user


def handler_with_typed_user_developer(
    user: AuthenticatedUser = Depends(require_developer_user),
) -> dict:
    if isinstance(user, dict):
        return {"ok": True}
    return user
