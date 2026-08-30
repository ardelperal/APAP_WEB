"""Domain validation helpers for the voluntarios slice (AGENTS.md §31: no I/O).

Validation errors are raised here, not in the adapter or routes.
The use cases call these helpers before delegating to the port.
"""
from __future__ import annotations


class VoluntarioValidationError(ValueError):
    """Raised when input validation fails.

    Subclasses :class:`ValueError` so existing ``except ValueError``
    clauses in callers keep working.
    """


def _require_non_blank(value: str | None, field_name: str) -> str:
    if value is None:
        raise VoluntarioValidationError(
            f"{field_name} es obligatorio"
        )
    stripped = value.strip()
    if not stripped:
        raise VoluntarioValidationError(
            f"{field_name} es obligatorio y no puede estar vacio"
        )
    return stripped


__all__ = ["VoluntarioValidationError", "_require_non_blank"]
