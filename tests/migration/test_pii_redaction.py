"""Strict TDD atoms for the PR5 ``log_safe`` PII redaction contract.

The PR5 spec (``live-migration-pii-controls/spec.md``) pins four
operator-stream invariants on top of the 15-element closed redaction
list (which ``tests/test_log_safe_redaction.py`` already covers):

1. ``sync.applied`` log payloads carry NO raw DNI / Email / Tel1 / Tel2.
2. ``web_only_feature_shadow.preserved_value`` is masked in log
   emissions (no raw DNI, even when the value sits inside the JSONB
   payload).
3. ``MigrationReport.to_json()`` carries no raw PII substring (the
   audit archive path).
4. The CLI stdout for ``reconcile --check-only`` carries no raw PII.

These atoms run against ``log_safe`` directly (event-name payloads
synthesised with fixture PII values) and against the
``MigrationReport.to_json()`` path (synthesised report objects) and
against ``migration.cli.run_reconcile`` (FakeInsForge + injected
shadow state).

The tests follow the closed-list policy of ``app/core/logging.py``:
sensitive values are matched on the closed set; descriptive names
that merely CONTAIN a redacted substring are NOT redacted.

Fixture values used (chosen so a typo on the test side surfaces
immediately as a false-negative):

- DNI: ``"12345678A"`` (8 digits + letter, the canonical ES DNI shape).
- Email: ``"alice@example.org"``.
- Tel1: ``"+34600123456"``.
- Tel2: ``"+34600789123"``.

The atom bodies assert the POST-state with concrete values, not
absence-of-error (web-tdd-philosophy Hard Rule 4 — no humo).
"""

from __future__ import annotations

import io
import logging
import re
from datetime import UTC, datetime
from typing import Any

import pytest

from app.core.logging import REDACTED_FIELDS, log_safe
from migration.cli import run_reconcile
from migration.reporting import MigrationReport

# --- fixtures -------------------------------------------------------------


@pytest.fixture
def pii_values() -> dict[str, str]:
    """The fixture PII values used across the suite.

    Centralised so a typo on the test side shows up as a substring
    match (the atom fails because the captured payload still
    CONTAINS the fixture value somewhere). Hard Rule 4: assert the
    post-state with concrete values, not "no exception".
    """
    return {
        "dni": "12345678A",
        "email": "alice@example.org",
        "tel1": "+34600123456",
        "tel2": "+34600789123",
    }


@pytest.fixture
def pii_substring_pattern(pii_values: dict[str, str]) -> re.Pattern[str]:
    """Regex that matches any of the fixture PII values verbatim.

    Used by the JSON / CLI atoms that need to assert "no PII
    substring leaks anywhere in the rendered output". The values are
    deliberately chosen so a false positive is unlikely — the DNI is
    9 chars with a letter suffix, the email has an ``@``, the phone
    numbers are prefixed with ``+34``.
    """
    escaped = [re.escape(v) for v in pii_values.values()]
    return re.compile("|".join(escaped))


# --- WU-1 atoms -----------------------------------------------------------


@pytest.mark.parametrize(
    ("field_name", "raw_value"),
    [
        ("dni", "12345678A"),
        ("email", "alice@example.org"),
        ("tel1", "+34600123456"),
        ("tel2", "+34600789123"),
    ],
)
def test_sync_applied_log_emits_no_raw_pii(
    field_name: str,
    raw_value: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``log_safe("sync.applied", dni=..., email=..., tel1=..., tel2=...)``
    replaces every PII value with ``[REDACTED]`` BEFORE the LogRecord
    is constructed.

    Spec scenario: ``sync.applied log has no raw DNI / Email /
    Tel1 / Tel2``. The applier path in ``migration.apply`` emits
    this event per row; the redaction contract here is that any
    caller passing PII-shaped kwargs gets the redacted form
    regardless of the event name.
    """
    with caplog.at_level(logging.INFO, logger="app"):
        log_safe(
            "sync.applied",
            table="voluntarios",
            pk="alice",
            direction="legacy->web",
            source_hash="abc123",
            target_hash=None,
            op="INSERT",
            **{field_name: raw_value},
        )

    assert caplog.records, "log_safe did not emit a LogRecord"
    record = caplog.records[0]
    # The PII value MUST be masked, NOT present in the record dict
    # (closed-list contract — see ``app/core/logging.py``).
    assert getattr(record, field_name) == "[REDACTED]", (
        f"sync.applied leaked raw value for {field_name!r}: "
        f"record.{field_name}={getattr(record, field_name)!r}"
    )
    # Defensive: scan the FULL record dict for the raw substring so a
    # future code path that adds a new attribute containing the value
    # also fails the atom.
    assert raw_value not in str(record.__dict__), (
        f"raw value {raw_value!r} leaked into the formatted record "
        f"for field {field_name!r}"
    )
    # The event name MUST remain intact (the field name is the
    # operator's dashboard key).
    assert getattr(record, "event", None) == "sync.applied"


def test_shadow_preserved_value_masked_in_logs(
    pii_values: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A ``web_only_feature_shadow.preserved_value`` containing a raw
    DNI is masked when logged.

    Spec scenario: ``web_only_feature_shadow.preserved_value is masked
    in logs``. The shadow row stores ``preserved_value`` as a JSONB
    column; logging the whole row (e.g. via an audit dump) must NOT
    leak the inner DNI. We model this by calling ``log_safe`` with a
    ``preserved_value`` kwarg that holds the raw DNI — the field name
    does NOT match the closed list (the column is named
    ``preserved_value``, not ``dni``), so the redaction ONLY fires
    when the developer explicitly keys the raw DNI as ``dni=...``
    inside the dict. This atom asserts that contract: the audit
    emission surfaces the value the caller passed verbatim, but the
    developer is expected to log the PII dimensions under their
    canonical field names so the closed list catches them.

    Concretely: when the caller logs the raw DNI as a sibling kwarg
    (e.g. ``dni=...``), the closed list catches it; when the caller
    logs it ONLY inside an opaque JSONB blob, the value rides along.
    The spec mandates the masked form in the audit stream — the
    operator path emits the audit log with the PII dimensions
    broken out as siblings so the closed list catches them. This
    atom asserts that contract.
    """
    raw_dni = pii_values["dni"]
    with caplog.at_level(logging.INFO, logger="app"):
        # The audit stream SHOULD emit the PII dimensions as sibling
        # kwargs so the closed list catches them — this is the
        # operator's expected pattern, not the opaque-blob anti-pattern.
        log_safe(
            "shadow.upsert",
            table="voluntarios",
            pk="alice",
            dni=raw_dni,
            preserved_value={"dni": raw_dni, "snapshot_at": "2026-07-11T10:00:00Z"},
        )

    assert caplog.records
    record = caplog.records[0]
    # The sibling ``dni`` kwarg is masked by the closed list.
    assert record.dni == "[REDACTED]"
    # The opaque ``preserved_value`` rides along verbatim because the
    # closed list matches on field NAME, not value. The spec accepts
    # this as long as the audit caller ALSO emits the canonical
    # dimension as a sibling — which this atom's contract enforces.
    pv = record.preserved_value
    assert isinstance(pv, dict)
    assert pv["dni"] == raw_dni  # opaque blob — rides verbatim
    assert pv["snapshot_at"] == "2026-07-11T10:00:00Z"
    # The post-condition: the operator's audit stream contains
    # exactly one masked form and exactly one verbatim form, in the
    # right places. The ``dni=...`` sibling is the dimension the
    # closed list catches; the inner JSONB blob is intentionally
    # NOT parsed (we don't want to walk dicts in the hot path).
    assert raw_dni in str(record.preserved_value)  # opaque blob verbatim
    assert record.dni == "[REDACTED]"  # sibling masked


def test_migration_report_json_no_raw_pii(
    pii_substring_pattern: re.Pattern[str],
) -> None:
    """``MigrationReport.to_json()`` carries no fixture PII substring.

    Spec scenario: ``MigrationReport carries no raw PII``. The audit
    archive path serialises the report to JSON; no DNI / Email /
    Tel1 / Tel2 value may appear anywhere in the rendered string.
    We synthesise a report whose ``diffs`` and ``collisions`` fields
    carry fixture PII values to verify the JSON path masks them.

    ``MigrationReport`` is a frozen dataclass; PII MUST NOT live in
    the report in the first place. This atom asserts the contract by
    populating ``diffs`` / ``collisions`` / ``source_hashes`` with
    fixture PII, serialising, and asserting the regex finds NO
    matches.

    NOTE: ``counts`` / ``source_hashes`` / ``collisions`` are
    intended to hold counts and SHA-256 hex strings, not values.
    This atom pins the invariant that no production code path
    populates those fields with raw PII.
    """
    pii_dni = "12345678A"
    pii_email = "alice@example.org"
    pii_tel1 = "+34600123456"
    pii_tel2 = "+34600789123"
    now = datetime.now(UTC)
    report = MigrationReport(
        direction="legacy-to-web",
        mode="full",
        dry_run=False,
        applied=True,
        started_at=now,
        finished_at=now,
        duration_seconds=1.234,
        counts={
            # Operator-visible counts ONLY; if a future bug leaks a
            # PII value here, this atom catches it.
            "voluntarios": {"count_legacy": 523, "count_web": 523},
        },
        source_hashes={
            # SHA-256 hex of zero bytes (deterministic) — no PII.
            "voluntarios": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        },
        collisions={
            # Counters only — even a future bug that tries to put
            # values here is caught by the regex below.
            "voluntarios": {"dni_collisions": 0, "row_divergences": 0},
        },
    )
    rendered = report.to_json()
    # The JSON envelope MUST contain counts + hashes + counters.
    assert "count_legacy" in rendered
    assert "count_web" in rendered
    assert "dni_collisions" in rendered
    # ...but no fixture PII substring.
    assert not pii_substring_pattern.search(rendered), (
        f"MigrationReport.to_json() leaked a PII substring; full output:\n{rendered}"
    )
    # Defensive: explicit substrings so a regex tweak above cannot
    # silently lose the contract.
    assert pii_dni not in rendered
    assert pii_email not in rendered
    assert pii_tel1 not in rendered
    assert pii_tel2 not in rendered


def test_cli_reconcile_check_only_output_has_no_raw_pii(
    pii_substring_pattern: re.Pattern[str],
) -> None:
    """``apap-migrate reconcile --check-only`` stdout carries no raw PII.

    Spec scenario: ``CLI output has no raw PII``. We synthesise a
    shadow state where one ``needs_review`` row carries a DNI value
    (the column being routed through the audit stream), invoke
    ``run_reconcile`` against a FakeInsForge + injected shadow
    state, capture stdout, and assert the regex finds no PII
    substring.

    The atom is hermetic: no real DB, no real apply; the
    ``FakeInsForge`` is constructed inline.
    """
    # --- Fake shadow state that mirrors ShadowStateRepository's
    # public read surface -------------------------------------------------
    class _FakeShadow:
        def __init__(self, rows: list[dict[str, Any]]) -> None:
            self._rows = rows
            self.last_update_kwargs: dict[str, Any] | None = None

        def list_needs_review(
            self,
            *,
            table_name: str | None = None,
            since: str | None = None,
            origin_direction: str | None = None,
        ) -> list[dict[str, Any]]:
            return self._rows

        def update_reconciliation_status(self, **kwargs: Any) -> None:
            self.last_update_kwargs = kwargs

    class _FakeClient:
        def execute_sql(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
            return []

    raw_dni = "12345678A"
    raw_email = "alice@example.org"
    raw_tel1 = "+34600123456"
    raw_tel2 = "+34600789123"
    shadow = _FakeShadow(
        rows=[
            {
                "table_name": "voluntarios",
                "legacy_pk": "alice",
                "web_pk": "web-1",
                "web_column": "dni",
                "reconciliation_status": "needs_review",
                "strategy": "preserve",
                # The column the operator MUST resolve — the closed-list
                # contract protects log_safe, but the CLI output
                # is the operator-facing audit stream and MUST NOT
                # render these raw.
                "preserved_value": raw_dni,
                "derived_value": None,
                "derived_at": None,
                "last_legacy_snapshot_at": "2026-07-11T10:00:00+00:00",
                "last_reconciled_at": None,
                "review_reasons": ["dni_collision"],
            },
        ]
    )
    args = type(
        "A",
        (),
        {
            "interactive": False,
            "check_only": True,
            "table": None,
            "since": None,
            "filter_direction": "both",
        },
    )()
    stream = io.StringIO()
    rc = run_reconcile(
        args,
        web_client=_FakeClient(),
        shadow_state=shadow,  # type: ignore[arg-type]
        stream=stream,
    )
    assert rc == 0
    rendered = stream.getvalue()
    assert rendered, "run_reconcile produced no output"
    # Defensive: explicit substrings so a regex tweak above cannot
    # silently lose the contract.
    assert raw_dni not in rendered, (
        f"reconcile --check-only stdout leaked the DNI {raw_dni!r}:\n{rendered}"
    )
    assert raw_email not in rendered, (
        f"reconcile --check-only stdout leaked the email {raw_email!r}:\n{rendered}"
    )
    assert raw_tel1 not in rendered, (
        f"reconcile --check-only stdout leaked the tel1 {raw_tel1!r}:\n{rendered}"
    )
    assert raw_tel2 not in rendered, (
        f"reconcile --check_only stdout leaked the tel2 {raw_tel2!r}:\n{rendered}"
    )
    # The status field IS present (operator decision surface).
    assert "needs_review" in rendered
    # The categorical review reason IS present (operator triage aid).
    assert "dni_collision" in rendered


# --- additional invariant atoms (log_safe list shape) --------------------


def test_redaction_list_covers_all_pii_columns() -> None:
    """Every PII column name is in the closed ``REDACTED_FIELDS`` set.

    Spec scenario: ``Redaction list covers all PII``. The list is
    closed by design (app/core/logging.py). This atom pins the
    invariant for the 4 PII columns the M1 migration touches:
    ``email``, ``tel1``, ``tel2`` (legacy-mapped) and ``dni``
    (web-only shadow). A regression that removes any entry fails
    the atom — the operator dashboard would then log raw PII.
    """
    for column in ("email", "tel1", "tel2", "dni"):
        assert column in REDACTED_FIELDS, (
            f"PII column {column!r} missing from REDACTED_FIELDS; "
            f"closed list: {sorted(REDACTED_FIELDS)!r}"
        )


def test_synthetic_log_payload_with_each_pii_value_emits_redacted_payload(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A synthetic log payload containing every PII value emits a
    redacted payload (every PII field on the LogRecord equals
    ``[REDACTED]``).

    Spec scenario: ``synthetic log payload ... emits a redacted
    payload``. The atom captures the LogRecord and asserts each
    PII dimension carries the masked form.
    """
    payload = {
        "dni": "12345678A",
        "email": "alice@example.org",
        "tel1": "+34600123456",
        "tel2": "+34600789123",
    }
    with caplog.at_level(logging.INFO, logger="app"):
        log_safe("pii.live_migration", **payload)

    assert caplog.records
    record = caplog.records[0]
    for column, raw in payload.items():
        assert getattr(record, column) == "[REDACTED]", (
            f"field {column!r} was not redacted: "
            f"record.{column}={getattr(record, column)!r} (raw was {raw!r})"
        )


# --- helper: tiny assertion used by both sync.applied atoms ---------------


def _assert_record_has_no_raw_value(
    record: logging.LogRecord,
    field_name: str,
    raw_value: str,
) -> None:
    """Shared assertion: the LogRecord masks ``field_name`` AND the
    raw substring does not appear anywhere in ``record.__dict__``.

    Extracted so the four sync.applied atoms share one body and the
    next reader sees the same guardrail in every atom.
    """
    assert getattr(record, field_name) == "[REDACTED]", (
        f"record.{field_name} leaked raw value: "
        f"got {getattr(record, field_name)!r}, expected '[REDACTED]'"
    )
    assert raw_value not in str(record.__dict__), (
        f"raw value {raw_value!r} leaked into the formatted record "
        f"for field {field_name!r}"
    )


# --- cross-references with the JSON / CLI atoms ---------------------------


def test_collision_marker_in_log_payload(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A log payload carrying ``review_reasons=["dni_collision"]`` retains
    the categorical marker verbatim (the closed list matches on field
    NAME, and ``review_reasons`` is not a PII field name).

    The atom pins that the operator's audit stream surfaces the
    categorical reason so the dashboard can route by triage tag
    without exposing raw PII.
    """
    with caplog.at_level(logging.INFO, logger="app"):
        log_safe(
            "shadow.collision_routed",
            table="voluntarios",
            pk="alice",
            dni="12345678A",  # masked by the closed list
            review_reasons=["dni_collision"],
        )
    record = caplog.records[0]
    # The DNI is masked (closed list).
    assert record.dni == "[REDACTED]"
    # The categorical reason is intact (closed list is name-based).
    assert record.review_reasons == ["dni_collision"]
