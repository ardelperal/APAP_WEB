"""Strict TDD atoms for the PR4b ``log_safe`` redaction list extension.

The redaction list grew from 12 to 15 fields to cover the PII columns the
M1 forward migration brings into the web: ``dni`` (web-only), ``tel1``,
``tel2``. This file pins the new entries individually AND the full
15-element shape so a regression in either direction is caught.
"""

from __future__ import annotations

import logging

import pytest

from app.core.logging import REDACTED_FIELDS, log_safe


def test_redacted_fields_set_has_exactly_fifteen_entries() -> None:
    """The closed list grows from 12 to 15 with the three new PII columns."""
    assert len(REDACTED_FIELDS) == 15, (
        f"REDACTED_FIELDS must be exactly 15 entries after PR4b extension; "
        f"got {len(REDACTED_FIELDS)}: {sorted(REDACTED_FIELDS)!r}"
    )


@pytest.mark.parametrize(
    "field_name",
    ["dni", "tel1", "tel2"],
)
def test_pr4b_redaction_list_includes_each_new_pii_field(
    field_name: str,
) -> None:
    """The three new PII fields are in the closed redaction list."""
    assert field_name in REDACTED_FIELDS, (
        f"{field_name!r} is a PR4b PII column and MUST be in REDACTED_FIELDS; "
        f"current set: {sorted(REDACTED_FIELDS)!r}"
    )


@pytest.mark.parametrize(
    "field_name",
    ["dni", "tel1", "tel2"],
)
def test_log_safe_redacts_each_new_pii_field_value(
    field_name: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A value passed as ``dni`` / ``tel1`` / ``tel2`` is replaced with ``[REDACTED]``."""
    secret_value = f"raw-{field_name}-12345678A"
    with caplog.at_level(logging.INFO, logger="app"):
        log_safe("pr4b.pii_test", **{field_name: secret_value})

    assert caplog.records, "log_safe did not emit a LogRecord"
    record = caplog.records[0]
    assert record._caller_fields[field_name] == "[REDACTED]", (
        f"log_safe leaked raw value for {field_name!r}: "
        f"record._caller_fields[{field_name}]={record._caller_fields.get(field_name)!r}"
    )
    assert secret_value not in str(record.__dict__), (
        f"raw value for {field_name!r} leaked into the formatted record"
    )


@pytest.mark.parametrize(
    ("field_name", "raw_value"),
    [
        ("dni", "12345678A"),
        ("tel1", "+34600123456"),
        ("tel2", "+34600789123"),
        ("DNI", "Y8765432B"),
        ("Tel1", "+1-555-0100"),
        ("TEL2", "+1-555-0200"),
    ],
)
def test_log_safe_redaction_is_case_insensitive_for_new_pii_fields(
    field_name: str,
    raw_value: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Mixed-case variants of ``dni`` / ``tel1`` / ``tel2`` are still redacted."""
    with caplog.at_level(logging.INFO, logger="app"):
        log_safe("pr4b.pii_case", **{field_name: raw_value})

    assert caplog.records
    record = caplog.records[0]
    assert record._caller_fields[field_name] == "[REDACTED]", (
        f"case variant {field_name!r} was not redacted: "
        f"record._caller_fields[{field_name}]={record._caller_fields.get(field_name)!r}"
    )
    assert raw_value not in str(record.__dict__)


def test_log_safe_does_not_leak_pii_via_record_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Raw ``DNI``, ``Tel1``, ``Tel2`` values MUST NOT appear in the formatted message."""
    with caplog.at_level(logging.INFO, logger="app"):
        log_safe(
            "pr4b.pii_message",
            dni="12345678A",
            tel1="+34600123456",
            tel2="+34600789123",
        )
    record = caplog.records[0]
    formatted = record.getMessage()
    assert "12345678A" not in formatted
    assert "+34600123456" not in formatted
    assert "+34600789123" not in formatted


def test_log_safe_descriptive_field_names_are_not_redacted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Descriptive names that merely CONTAIN a redacted substring pass through."""
    with caplog.at_level(logging.INFO, logger="app"):
        log_safe(
            "pr4b.descriptive",
            dni_lookup_table="voluntarios",
            telefono_secundario="+34600999888",
        )
    record = caplog.records[0]
    # Descriptive names that contain substrings of redacted fields are NOT
    # redacted per the closed-list contract.
    assert record._caller_fields["dni_lookup_table"] == "voluntarios"
    assert record._caller_fields["telefono_secundario"] == "+34600999888"
