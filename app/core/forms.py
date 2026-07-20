"""Shared normalization and validation helpers for submitted form values."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def optional_value(value: Any) -> str | None:
    """Strip a value and normalize missing or blank input to ``None``."""
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def optional_text(params: Mapping[str, Any], field: str) -> str | None:
    """Read an optional text field, normalizing missing or blank input."""
    return optional_value(params.get(field))


def required_text(
    params: Mapping[str, Any],
    field: str,
    *,
    error_template: str = "{field} is required and cannot be empty",
) -> str:
    """Read a required text field or raise ``ValueError`` when blank."""
    value = optional_text(params, field)
    if value is None:
        raise ValueError(error_template.format(field=field))
    return value


__all__ = ["optional_text", "optional_value", "required_text"]
