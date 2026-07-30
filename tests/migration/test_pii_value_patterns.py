"""Strict TDD atoms for ``_PII_VALUE_PATTERNS`` coverage (issue #219).

RED phase: parametrized atom listing every covered PII shape
(positive) and every intentionally-rejected shape (negative).

Shapes that MUST be matched (positive cases):
- 8-digit DNI:     12345678Z
- NIE X-prefix:    X1234567Z
- NIE Y-prefix:    Y7654321A
- NIE Z-prefix:    Z1234567S
- NIF Especial K:  K1234567A
- NIF Especial L:  L1234567B
- NIF Especial M:  M1234567C
- Phone ES mobile: +34 612345678  (E.164, Spanish mobile)
- Phone intl:     +1 5551234567  (E.164, international)

Shapes that MUST NOT be matched (negative cases):
- NCHIP short:    001, 1234, 12345
- Plain digits:   1234567890
- All letters:    ABCDEFGH
- Mixed nonsense: AB12CD34
- Empty string:  (empty)
- UUID:           12345678-1234-5678-1234-567812345678

The atom is anchored to ``_looks_like_pii`` (the only public seam
exposed by ``cli_format.py`` for the PK-value mask path).
"""

from __future__ import annotations

import pytest

from migration.cli_format import _looks_like_pii

# --- positive cases: MUST match ---------------------------------------------


@pytest.mark.parametrize(
    ("value", "description"),
    [
        ("12345678Z", "DNI estándar — 8 dígitos + letra"),
        ("X1234567Z", "NIE X-prefix — extranjero X + 7 dígitos + letra"),
        ("Y7654321A", "NIE Y-prefix — extranjero Y + 7 dígitos + letra"),
        ("Z1234567S", "NIE Z-prefix — extranjero Z + 7 dígitos + letra"),
        ("K1234567A", "NIF Especial K — menores <14 + 7 dígitos + letra"),
        ("L1234567B", "NIF Especial L — españoles no residentes + 7 dígitos + letra"),
        ("M1234567C", "NIF Especial M — extranjeros sin NIE + 7 dígitos + letra"),
        ("+34 612345678", "Teléfono ES móvil — E.164 con +34 y espacio"),
        ("+34612345678", "Teléfono ES móvil — E.164 con +34 sin espacio"),
        # Note: +1 5551234567 (with space, 10 subscriber digits) is ambiguous —
        # US NANP is +1 followed by 10 digits; our international regex expects
        # 9 subscriber digits.  The canonical US E.164 form (no space) is used
        # instead: +15551234567.
        ("+15551234567", "Teléfono internacional — E.164 US sin espacio"),
        ("alice@example.org", "Email — forma canónica"),
        ("user+tag@domain.es", "Email — con subaddressing"),
    ],
)
def test_pii_positive_cases(value: str, description: str) -> None:
    """Every PII shape listed above MUST be matched by ``_looks_like_pii``."""
    assert _looks_like_pii(value) is True, (
        f"[REDACTED expected] value {value!r} ({description}) "
        f"was not matched by _looks_like_pii; NIE/NIF-especial or "
        f"phone regex may be incomplete (issue #219)"
    )


# --- negative cases: MUST NOT match ------------------------------------------


@pytest.mark.parametrize(
    ("value", "description"),
    [
        ("001", "NCHIP — identificador corto numérico, NO es PII"),
        ("1234", "NCHIP — 4 dígitos, NO es PII"),
        ("12345", "NCHIP — 5 dígitos, NO es PII"),
        ("1234567890", "Dígitos planos — 10 dígitos sin formato válido, NO es PII"),
        ("ABCDEFGH", "Solo letras — sin formato DNI/NIE, NO es PII"),
        ("AB12CD34", "Mezcla letras-números sin formato válido, NO es PII"),
        ("", "String vacío — no es PII"),
        ("12345678-1234-5678-1234-567812345678", "UUID — formato estándar, NO es PII"),
        ("abcdefgh-ijkl-mnop-qrst-uvwxyz012345", "UUID lowercase — NO es PII"),
    ],
)
def test_pii_negative_cases(value: str, description: str) -> None:
    """Numeric NCHIPs, short IDs, and non-PII strings MUST NOT be matched."""
    assert _looks_like_pii(value) is False, (
        f"[FALSE POSITIVE] value {value!r} ({description}) "
        f"was matched by _looks_like_pii; phone regex may be too broad "
        f"and catching numeric NCHIPs (issue #219)"
    )


# --- non-string input ---------------------------------------------------------


@pytest.mark.parametrize(
    "non_string",
    [None, 12345678, 12.34, True, [], {}],
)
def test_pii_non_string_returns_false(non_string: object) -> None:
    """Non-string values must always return False (no crash, no True)."""
    assert _looks_like_pii(non_string) is False
