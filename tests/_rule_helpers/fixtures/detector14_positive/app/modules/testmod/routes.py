"""Positive fixture: ``user: Any = Depends(...)`` on auth deps — must be flagged."""

from typing import Any

from fastapi import Depends

from app.core.auth_dependencies import (
    require_authorized_user,
    require_developer_user,
    require_writer_user,
)


def handler_with_any_user_authorized(
    user: Any = Depends(require_authorized_user),
) -> dict:
    if isinstance(user, dict):
        return {"ok": True}
    return user


def handler_with_any_user_writer(
    data: str,
    user: Any = Depends(require_writer_user),
) -> dict:
    if isinstance(user, dict):
        return {"ok": True, "data": data}
    return user


def handler_with_any_user_developer(
    user: Any = Depends(require_developer_user),
) -> dict:
    if isinstance(user, dict):
        return {"ok": True}
    return user
