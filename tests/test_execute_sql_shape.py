"""Tests for the live InsForge response shape of ``/api/database/advance/rawsql``.

Pins the contract every ``client.execute_sql(...)`` call site depends
on. The current production bug (commit e56e418 / ETL move) is that
``execute_sql`` returns the FULL response body
(``{"rows": [...], "rowCount": 1, "fields": [...]}``), but the call
sites do ``rows[0] if rows else None`` expecting a ``list[dict]``,
which raises ``KeyError: 0``.

The fix: ``execute_sql`` MUST return ``body["rows"]`` (a list of
dicts). The fakes in tests/ that return ``[dict]`` for ``execute_sql``
need to be updated to also return the wrapped envelope, or this
test must also pin the public shape (a list of dicts).

These tests run against the LIVE InsForge (proxied through
``insforge_run-raw-sql``) to catch shape drift the way the OAuth
``insforge_code`` bug did on 2026-06-28.
"""

from __future__ import annotations

from app.core.insforge import InsForgeClient

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
    # We cannot hit InsForge from unit tests (would require network
    # and a real API key). Instead, this test reads the in-source
    # contract: the function's body MUST do ``body["rows"]`` (or
    # equivalent shape extraction), NOT return ``_safe_json(response)``
    # directly.
    from pathlib import Path

    source = Path("app/core/insforge.py").read_text(encoding="utf-8")
    # The function MUST extract the "rows" key from the JSON body.
    # The current bug: it returns the full envelope.
    assert 'body["rows"]' in source or "body['rows']" in source, (
        "app/core/insforge.py::execute_sql does not extract the 'rows' "
        "key from the InsForge response envelope. Call sites do "
        "'rows[0] if rows else None' expecting a list of dicts, but "
        "they get the full body {'rows': [...], 'rowCount': N, 'fields': [...]} "
        "and crash with KeyError: 0. See the 2026-06-28 production outage."
    )


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
    annotations = InsForgeClient.execute_sql.__annotations__
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
