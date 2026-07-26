"""Tests for startup secret validation: _validate_secrets and StartupConfigError.

Covers REQ-1..REQ-5, REQ-7, REQ-8 from the spec.

The contract:
- Empty insforge_service_key  → StartupConfigError(env_var="APAP_INSFORGE_SERVICE_KEY")
- Placeholder session_secret   → StartupConfigError(env_var="APAP_SESSION_SECRET", reason="placeholder")
- Short session_secret (<32)  → StartupConfigError(env_var="APAP_SESSION_SECRET", reason="too_short")
- debug=True                  → all checks bypassed
- Valid secrets               → returns None
- Error message NEVER echoes the secret value
- log_safe emitted BEFORE raise, with no secret value in any kwarg
"""

from __future__ import annotations

import pytest

from app.core import config as config_module
from app.core.config import (
    _PLACEHOLDER_SESSION_SECRET,
    StartupConfigError,
    _validate_secrets,
)

# ---------------------------------------------------------------------------
# Parametrized unit tests for _validate_secrets
# ---------------------------------------------------------------------------


class TestValidateSecretsRejections:
    """REQ-1, REQ-2, REQ-3: three failure modes."""

    def test_empty_insforge_service_key_raises(self) -> None:
        """REQ-1: empty insforge_service_key triggers StartupConfigError."""
        settings = config_module.Settings(
            _env_file=None,
            insforge_service_key="",
            session_secret="x" * 32,
        )
        with pytest.raises(StartupConfigError) as exc_info:
            _validate_secrets(settings)
        assert "APAP_INSFORGE_SERVICE_KEY" in str(exc_info.value)
        # REQ-8: error message MUST NOT echo the empty secret value
        assert '""' not in str(exc_info.value)
        assert "''" not in str(exc_info.value)

    def test_placeholder_session_secret_raises(self) -> None:
        """REQ-2: placeholder session_secret triggers StartupConfigError."""
        settings = config_module.Settings(
            _env_file=None,
            insforge_service_key="ik_test_key",
            session_secret=_PLACEHOLDER_SESSION_SECRET,
        )
        with pytest.raises(StartupConfigError) as exc_info:
            _validate_secrets(settings)
        assert "APAP_SESSION_SECRET" in str(exc_info.value)
        assert "placeholder" in str(exc_info.value)
        # REQ-8: message must NOT contain the placeholder string
        assert _PLACEHOLDER_SESSION_SECRET not in str(exc_info.value)

    def test_short_session_secret_raises(self) -> None:
        """REQ-3: session_secret shorter than 32 chars triggers StartupConfigError."""
        settings = config_module.Settings(
            _env_file=None,
            insforge_service_key="ik_test_key",
            session_secret="x" * 31,
        )
        with pytest.raises(StartupConfigError) as exc_info:
            _validate_secrets(settings)
        assert "APAP_SESSION_SECRET" in str(exc_info.value)
        assert "too_short" in str(exc_info.value)
        # REQ-8: message must NOT contain the short secret
        assert ("x" * 31) not in str(exc_info.value)

    def test_placeholder_is_exactly_the_sentinel(self) -> None:
        """The sentinel string must be the one used as the field default."""
        settings = config_module.Settings(
            _env_file=None,
            insforge_service_key="ik_test_key",
            session_secret="dev-only-change-me-in-production",
        )
        with pytest.raises(StartupConfigError) as exc_info:
            _validate_secrets(settings)
        # Must raise on the actual default value used in Settings
        assert "placeholder" in str(exc_info.value)


class TestValidateSecretsPass:
    """REQ-4: valid configuration passes cleanly."""

    def test_valid_secrets_pass(self) -> None:
        """Non-placeholder 32+ char secret and non-empty service key pass."""
        settings = config_module.Settings(
            _env_file=None,
            insforge_service_key="ik_test_key",
            session_secret="x" * 32,
        )
        # Must not raise
        _validate_secrets(settings)

    def test_33_char_secret_also_passes(self) -> None:
        """32 chars is the minimum; 33 also passes."""
        settings = config_module.Settings(
            _env_file=None,
            insforge_service_key="ik_test_key",
            session_secret="x" * 33,
        )
        _validate_secrets(settings)


class TestValidateSecretsDebugBypass:
    """REQ-5: debug=True bypasses all validation."""

    def test_debug_bypasses_empty_service_key(self) -> None:
        """debug=True + empty insforge_service_key → no exception."""
        settings = config_module.Settings(
            _env_file=None,
            debug=True,
            insforge_service_key="",
            session_secret=_PLACEHOLDER_SESSION_SECRET,
        )
        # Must not raise
        _validate_secrets(settings)

    def test_debug_bypasses_placeholder_secret(self) -> None:
        """debug=True + placeholder session_secret → no exception."""
        settings = config_module.Settings(
            _env_file=None,
            debug=True,
            insforge_service_key="",
            session_secret=_PLACEHOLDER_SESSION_SECRET,
        )
        _validate_secrets(settings)

    def test_debug_bypasses_short_secret(self) -> None:
        """debug=True + short session_secret → no exception."""
        settings = config_module.Settings(
            _env_file=None,
            debug=True,
            insforge_service_key="ik_test_key",
            session_secret="x",
        )
        _validate_secrets(settings)


# ---------------------------------------------------------------------------
# REQ-7: log_safe invariant — no secret value in any log kwarg
# ---------------------------------------------------------------------------


def test_log_safe_payload_omits_secret_value() -> None:
    """log_safe is called BEFORE raise, and NEVER passes the secret value as a kwarg.

    We trigger the placeholder rejection and verify the captured log record
    contains the env_var and reason but does NOT contain the placeholder sentinel.
    """
    captured_records: list[tuple[str, dict[str, object]]] = []

    def _capture_log(event: str, **kwargs: object) -> None:
        captured_records.append((event, dict(kwargs)))

    settings = config_module.Settings(
        _env_file=None,
        insforge_service_key="ik_test_key",
        session_secret=_PLACEHOLDER_SESSION_SECRET,
    )

    # Patch log_safe in the module where _validate_secrets uses it
    original = config_module.log_safe
    config_module.log_safe = _capture_log
    try:
        with pytest.raises(StartupConfigError):
            _validate_secrets(settings)
    finally:
        config_module.log_safe = original

    # Exactly one log call
    assert len(captured_records) == 1, f"expected exactly 1 log call, got {len(captured_records)}"
    event, kwargs = captured_records[0]

    # Event name
    assert event == "startup.config_invalid"

    # env_var is present
    assert "env_var" in kwargs
    assert kwargs["env_var"] == "APAP_SESSION_SECRET"

    # reason is present
    assert "reason" in kwargs
    assert kwargs["reason"] == "placeholder"

    # The sentinel placeholder value is NEVER passed as any kwarg value
    for k, v in kwargs.items():
        if isinstance(v, str):
            assert _PLACEHOLDER_SESSION_SECRET not in v, (
                f"secret value appeared in kwarg {k!r}; log_safe must never receive the secret"
            )


def test_error_message_does_not_echo_secret_value() -> None:
    """REQ-8: StartupConfigError message names env var but never echoes the value."""
    settings = config_module.Settings(
        _env_file=None,
        insforge_service_key="ik_test_key",
        session_secret="A" * 31,  # 31 chars → too_short; clearly a secret value
    )
    with pytest.raises(StartupConfigError) as exc_info:
        _validate_secrets(settings)
    msg = str(exc_info.value)
    # Must contain the env var name
    assert "APAP_SESSION_SECRET" in msg
    # Must NOT contain the actual short secret
    assert ("A" * 31) not in msg
