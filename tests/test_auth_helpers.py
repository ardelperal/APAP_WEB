"""Tests for canonical email identity helpers (app/core/auth_helpers.py).

Issue #277 / #278 — ghost users from mixed-case email identity.
"""

from __future__ import annotations

import pytest

from app.core.auth_helpers import normalize_email, validate_email_format


class TestNormalizeEmail:
    """GIVEN a mixed-case email with surrounding whitespace."""

    def test_strips_and_lowercases(self) -> None:
        """normalize_email(" Maria.Lopez@Gmail.com ") -> "maria.lopez@gmail.com".

        The function applies strip() then lower(). It does NOT remove dots.
        """
        result = normalize_email(" Maria.Lopez@Gmail.com ")
        assert result == "maria.lopez@gmail.com"

    def test_is_stable_for_already_canonical_input(self) -> None:
        """normalize_email("foo@bar.com") -> "foo@bar.com"."""
        result = normalize_email("foo@bar.com")
        assert result == "foo@bar.com"


class TestValidateEmailFormat:
    """Format validation at the service boundary."""

    def test_valid_email_passes(self) -> None:
        """validate_email_format("foo@bar.com") -> no raise."""
        validate_email_format("foo@bar.com")  # must not raise

    def test_missing_at_sign_raises_value_error(self) -> None:
        """validate_email_format("invalid") -> raises ValueError."""
        with pytest.raises(ValueError, match="email format invalid"):
            validate_email_format("invalid")

    def test_empty_string_raises_value_error(self) -> None:
        """validate_email_format("") -> raises ValueError."""
        with pytest.raises(ValueError, match="email cannot be empty"):
            validate_email_format("")

    def test_at_sign_only_raises_value_error(self) -> None:
        """validate_email_format("@foo.com") -> raises ValueError."""
        with pytest.raises(ValueError, match="email format invalid"):
            validate_email_format("@foo.com")
