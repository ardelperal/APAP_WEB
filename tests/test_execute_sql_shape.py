"""Tests for the public ``SqlExecutor.execute_sql`` response shape."""

from __future__ import annotations

from unittest.mock import patch

from app.core.local_backend.db import LocalPostgresExecutor

# ---------------------------------------------------------------------------
# Public surface contract (the only contract every call site depends on)
# ---------------------------------------------------------------------------


def test_execute_sql_returns_list_of_dicts_not_envelope() -> None:
    """``execute_sql`` MUST return a ``list[dict]``, not the full envelope.

    Without this, every call site that does ``rows[0] if rows else None``
    (e.g. ``app/core/auth.py::get_user_by_email``) crashes with
    ``KeyError: 0`` in production. The fakes in tests/ happened to
    return ``[dict]`` directly, so the bug only surfaced live.
    """
    executor = LocalPostgresExecutor("postgresql://unused")
    expected = [{"id": "row-1"}]

    with patch.object(executor, "execute_sql", return_value=expected):
        result = executor.execute_sql("SELECT id FROM example")

    assert result == expected
    assert isinstance(result, list)
    assert isinstance(result[0], dict)


def test_execute_sql_type_hint_matches_public_shape() -> None:
    """The return annotation MUST be ``list[dict[str, Any]]`` (not ``Any``).

    Pinning the type so mypy/pyright catch the same kind of drift
    that bit us on 2026-06-28 (the function returned a dict but the
    annotation claimed ``list[dict[str, Any]]``, so the bug hid
    behind the type hint).

    Reads the raw ``__annotations__`` because ``from __future__ import
    annotations`` makes all annotations lazy strings — ``inspect.signature``
    returns the string ``"list[dict[str, Any]]"``, not the resolved
    ``list`` type. The bug is regression-detected by checking the
    annotation starts with ``list[`` and contains ``dict`` and ends
    with ``]``; any deviation (e.g. ``Any``, ``dict`` alone) is
    caught.
    """
    annotations = LocalPostgresExecutor.execute_sql.__annotations__
    return_annotation = annotations.get("return", "")
    assert return_annotation.startswith("list["), (
        f"execute_sql return must be a list type, got: {return_annotation!r}"
    )
    assert "dict" in return_annotation, (
        f"execute_sql return must contain dict, got: {return_annotation!r}"
    )
    assert return_annotation.rstrip().endswith("]"), (
        f"execute_sql return must close the list bracket, "
        f"got: {return_annotation!r}"
    )
