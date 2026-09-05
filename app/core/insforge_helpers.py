"""Validation and parsing helpers for the InsForge HTTP client.

Split from ``app/core/insforge.py`` on 2026-09-05 to keep the client
file under the mutation-site ratchet baseline (AGENTS.md rule 21).
The helpers here are pure (no class-level state, no I/O beyond
``_safe_json`` which takes an httpx.Response).

Importing this module is safe; it has no side effects.
"""
from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.core.data_access import InsForgeError

_SAFE_BUCKET_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


def _validate_bucket_name(bucket_name: str) -> str:
    """Return a safe bucket name or raise before any HTTP call."""
    if not _SAFE_BUCKET_NAME.match(bucket_name):
        raise ValueError(
            f"unsafe bucket name {bucket_name!r}; must match {_SAFE_BUCKET_NAME.pattern}"
        )
    return bucket_name


# Issue #224: ``key`` (an animal photo filename, e.g. ``NombreFoto``) is
# interpolated directly into storage URL paths (``download_object_stream``,
# ``delete_object``) and sent as a JSON ``filename`` field
# (``_request_upload_strategy``). Unlike ``bucket``, it previously went
# through no format check at all — only a non-emptiness check in the retired
# animal service. This mirrors ``_validate_bucket_name``:
# an allow-list of filename-safe characters (letters, digits, ``_``, ``-``,
# ``.`` for extensions) that still rejects ``/``, ``\``, any ``..``
# segment, and a leading dot (hidden-file / relative-traversal payloads).
_SAFE_STORAGE_KEY = re.compile(r"^[A-Za-z0-9_.-]+$")



def _validate_bucket_name(bucket_name: str) -> str:
    """Return a safe bucket name or raise before any HTTP call."""
    if not _SAFE_BUCKET_NAME.match(bucket_name):
        raise ValueError(
            f"unsafe bucket name {bucket_name!r}; must match {_SAFE_BUCKET_NAME.pattern}"
        )
    return bucket_name


# Issue #224: ``key`` (an animal photo filename, e.g. ``NombreFoto``) is
# interpolated directly into storage URL paths (``download_object_stream``,
# ``delete_object``) and sent as a JSON ``filename`` field
# (``_request_upload_strategy``). Unlike ``bucket``, it previously went
# through no format check at all — only a non-emptiness check in the retired
# animal service. This mirrors ``_validate_bucket_name``:
# an allow-list of filename-safe characters (letters, digits, ``_``, ``-``,
# ``.`` for extensions) that still rejects ``/``, ``\``, any ``..``
# segment, and a leading dot (hidden-file / relative-traversal payloads).
_SAFE_STORAGE_KEY = re.compile(r"^[A-Za-z0-9_.-]+$")


def _validate_storage_key(key: str) -> str:
    """Return a safe storage key or raise before any HTTP call.

    Same fail-fast contract as :func:`_validate_bucket_name`: reject
    path separators, ``..`` traversal segments, and a leading dot,
    while still accepting ordinary photo filenames such as
    ``foto123.jpg`` or ``animal-123.png``.
    """
    if not _SAFE_STORAGE_KEY.match(key) or ".." in key or key.startswith("."):
        raise ValueError(
            f"unsafe storage key {key!r}; must match {_SAFE_STORAGE_KEY.pattern} "
            "with no path separators, '..' segments, or leading dot"
        )
    return key


def _extract_bucket_items(body: Any) -> list[Any]:
    """Normalize InsForge bucket list response shapes."""
    if isinstance(body, dict):
        buckets = body.get("buckets", body.get("data", []))
    else:
        buckets = body
    if isinstance(buckets, dict):
        return list(buckets.values())
    if isinstance(buckets, list):
        return buckets
    return []


def _bucket_name_from_item(item: Any) -> str | None:
    """Extract the bucket name from documented and MCP-shaped items."""
    if isinstance(item, str):
        return item
    if not isinstance(item, dict):
        return None
    for key in ("bucketName", "name", "bucket", "id"):
        value = item.get(key)
        if isinstance(value, str):
            return value
    return None


def _bucket_visibility_from_item(item: Any) -> bool | None:
    """Extract bucket visibility, or ``None`` when the API omits it."""
    if not isinstance(item, dict):
        return None
    for key in ("isPublic", "is_public", "public"):
        value = item.get(key)
        if isinstance(value, bool):
            return value
    return None


def _require_private_bucket(bucket_name: str, bucket: dict[str, Any]) -> None:
    """Fail closed unless bucket read-back proves ``isPublic`` is False."""
    visibility = bucket.get("isPublic")
    if visibility is False:
        return
    if visibility is True:
        raise InsForgeError(
            409,
            {
                "error": "bucket_public_violation",
                "message": f"Bucket {bucket_name!r} exists but is public; recreate it private",
            },
        )
    raise InsForgeError(
        502,
        {
            "error": "bucket_visibility_unknown",
            "message": f"Bucket {bucket_name!r} visibility could not be verified",
        },
    )


def _safe_json(response: httpx.Response) -> Any:
    """Parse JSON or return raw text if the body is not JSON."""
    try:
        return response.json()
    except (ValueError, json.JSONDecodeError):
        return response.text

