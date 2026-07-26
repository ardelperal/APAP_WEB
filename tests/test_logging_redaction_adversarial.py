"""Adversarial redaction tests for ``app.core.logging`` (PR-6A).

The redaction list is intentionally closed and conservative: a kwarg
name is redacted if and only if its normalized form matches an entry
in ``REDACTED_FIELDS``. These tests pin the boundary:

- Common variants (dashes, mixed case, uppercase) — MUST redact.
- Descriptive names that merely contain a redacted substring — MUST
  NOT redact (e.g. ``user_email_address``).
- Orthographic splits (e.g. ``e_mail``) — MUST NOT redact
  (closed-list policy).

Spec: ``openspec/changes/hardening-2026-q2/specs/06-structured-logging/spec.md``
Round-2 fix SB-5: 12-field redaction list.
"""

from __future__ import annotations

import logging

import pytest

from app.core.logging import log_safe

# Every (kwarg_name, secret_value) pair that MUST be redacted.
# Covers all 12 entries from REDACTED_FIELDS in their common variants.
REDACTED_VARIANTS = [
    ("email", "victim@example.com"),
    ("Email", "victim@example.com"),
    ("EMAIL", "victim@example.com"),
    ("session_token", "abc.def.ghi"),
    ("Session_Token", "abc.def.ghi"),
    ("SESSION_TOKEN", "abc.def.ghi"),
    ("session-token", "abc.def.ghi"),  # dash variant
    ("Session-Token", "abc.def.ghi"),
    ("jwt", "header.payload.signature"),
    ("JWT", "header.payload.signature"),
    ("oauth_code", "4/0AY0e-g7..."),
    ("OAuth_Code", "4/0AY0e-g7..."),
    ("pkce_verifier", "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"),
    ("PKCE_VERIFIER", "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"),
    ("csrf_token", "AbC123-token-from-callback"),
    ("CSRF_TOKEN", "AbC123-token-from-callback"),
    ("Csrf-Token", "AbC123-token-from-callback"),
    ("pkce_challenge", "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"),
    ("authorization", "Bearer abc.def.ghi"),
    ("Authorization", "Bearer abc.def.ghi"),
    ("cookie", "apap_session=xyz"),
    ("Cookie", "apap_session=xyz"),
    ("referer", "https://attacker.example/"),
    ("Referer", "https://attacker.example/"),
    ("ip_address", "10.0.0.42"),
    ("IP_ADDRESS", "10.0.0.42"),
    ("x_forwarded_for", "203.0.113.1"),
    ("X-Forwarded-For", "203.0.113.1"),
    ("X_FORWARDED_FOR", "203.0.113.1"),
]


# Field names that MUST NOT be redacted even though they LOOK sensitive.
NOT_REDACTED_VARIANTS = [
    ("user_email_address", "ana@example.com"),
    ("userEmail", "ana@example.com"),
    ("e_mail", "ana@example.com"),  # orthographic split
    ("emailaddr", "ana@example.com"),  # no separator
    ("session_token_hash", "sha256=..."),  # descriptive suffix
    ("csrf_token_age_seconds", "42"),  # meta, not the secret
    ("cookie_consent", "true"),  # looks like cookie but isn't a cookie value
    ("authorization_header_present", "true"),  # boolean metadata
    ("path", "/admin/users"),
    ("status_code", 200),
    ("reason", "token_mismatch"),
    ("voluntario_id", "v-123"),
]


@pytest.mark.parametrize("field_name,secret", REDACTED_VARIANTS)
def test_adversarial_redaction_redacts_variant(
    field_name: str, secret: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Every common variant of a closed-list name MUST be redacted."""
    with caplog.at_level(logging.INFO, logger="app"):
        log_safe("test.event", **{field_name: secret})

    record = caplog.records[0]
    stored_value = record._caller_fields[field_name]
    assert stored_value == "[REDACTED]", (
        f"{field_name!r} leaked: stored={stored_value!r} (secret={secret!r})"
    )
    assert secret not in str(record.__dict__), (
        f"secret for {field_name!r} leaked into the LogRecord: {record.__dict__!r}"
    )


@pytest.mark.parametrize("field_name,value", NOT_REDACTED_VARIANTS)
def test_adversarial_redaction_passes_through_descriptive_names(
    field_name: str, value: object, caplog: pytest.LogCaptureFixture
) -> None:
    """Descriptive or orthographic-split names MUST NOT be redacted.

    Closed-list policy: adding new names is a code-review decision.
    Names that merely resemble a redacted name keep their value so
    operators can see metadata (e.g. ``cookie_consent``).
    """
    with caplog.at_level(logging.INFO, logger="app"):
        log_safe("test.event", **{field_name: value})

    record = caplog.records[0]
    assert record._caller_fields[field_name] == value, (
        f"{field_name!r} was wrongly redacted to "
        f"{record._caller_fields.get(field_name)!r}; closed-list policy says only "
        f"exact (case/dash-normalized) matches redact."
    )


def test_adversarial_redaction_handles_all_twelve_fields_together(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """All 12 fields in one call site: every one becomes '[REDACTED]'.

    Round-2 fix SB-5 invariant: if anyone removes a field from
    REDACTED_FIELDS this test will surface it (the assertion checks
    every entry on the emitted record).
    """
    from app.core.logging import REDACTED_FIELDS

    kwargs = {name: f"secret-{name}" for name in REDACTED_FIELDS}
    with caplog.at_level(logging.INFO, logger="app"):
        log_safe("test.event", **kwargs)

    record = caplog.records[0]
    for name in REDACTED_FIELDS:
        assert record._caller_fields[name] == "[REDACTED]", (
            f"field {name!r} leaked: "
            f"{record._caller_fields.get(name)!r}"
        )
    # No secret appears anywhere on the record.
    record_dump = str(record.__dict__)
    for name in REDACTED_FIELDS:
        assert f"secret-{name}" not in record_dump


def test_adversarial_mixed_redacted_and_safe_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Mixed call: PII redacted, non-PII passthrough, no cross-contamination."""
    with caplog.at_level(logging.INFO, logger="app"):
        log_safe(
            "test.event",
            email="victim@example.com",
            path="/admin/users",
            status_code=403,
            reason="token_mismatch",
            voluntario_id="v-123",
        )

    record = caplog.records[0]
    assert record._caller_fields["email"] == "[REDACTED]"
    assert record._caller_fields["path"] == "/admin/users"
    assert record._caller_fields["status_code"] == 403
    assert record._caller_fields["reason"] == "token_mismatch"
    assert record._caller_fields["voluntario_id"] == "v-123"
    assert "victim@example.com" not in str(record.__dict__)


# --- T5 RED: adversarial LogRecord-attr-name collisions (issues #283, #284) ---


_LOGRECORD_COLLISION_KWARGS = [
    ("module", "voluntarios"),
    ("name", "app.extra"),
    ("process", 12345),
    ("levelname", "WARNING"),
    ("pathname", "/some/path"),
    ("taskName", "my-task"),
]


@pytest.mark.parametrize("attr_name,attr_value", _LOGRECORD_COLLISION_KWARGS)
def test_no_keyerror_on_logrecord_attr_name_kwarg(
    attr_name: str,
    attr_value: object,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """T5.1 RED: log_safe with module=/name=/process= etc.

    After the nested-envelope refactor, these kwarg names no longer collide
    with LogRecord's own attributes because they live inside record._caller_fields,
    not as top-level extra keys.
    """
    with caplog.at_level(logging.INFO, logger="app"):
        log_safe("test.collision", **{attr_name: attr_value})

    assert caplog.records, "log_safe did not emit a LogRecord"
    record = caplog.records[0]
    assert attr_name in record._caller_fields, (
        f"kwarg {attr_name!r} not stored in _caller_fields"
    )
    assert record._caller_fields[attr_name] == attr_value, (
        f"_caller_fields[{attr_name!r}] = {record._caller_fields.get(attr_name)!r}, "
        f"expected {attr_value!r}"
    )
