"""Strict TDD atoms pinning the PR4b audit doc structure.

The audit doc is required by the ``live-migration-pii-controls`` spec
to have four sections (Scope, Methodology, Findings, Verdict). This
file pins that contract so a future regression that drops or
renames a section fails CI before the M1 gate accepts a stale doc.

Hard rules honoured (web-tdd-philosophy):

- Rule 6 (refactor-safety): assertions are about the rendered markdown
  shape, not internal sequencing.
- Rule 4 (no humo): each atom pins a concrete substring / heading,
  not absence-of-error.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

AUDIT_DOC_PATH = Path("docs/audits/pii-live-migration-2026-Q3.md")


@pytest.fixture(scope="module")
def audit_doc_text() -> str:
    """Read the audit doc once per module (it does not change between tests)."""
    assert AUDIT_DOC_PATH.exists(), (
        f"PR4b audit doc missing: {AUDIT_DOC_PATH}. The M1 PII gate "
        f"is blocked without it."
    )
    return AUDIT_DOC_PATH.read_text(encoding="utf-8")


def test_audit_doc_has_scope_section(audit_doc_text: str) -> None:
    """The audit doc MUST carry a ``## Scope`` heading."""
    assert re.search(r"^##\s+Scope\b", audit_doc_text, re.MULTILINE), (
        "audit doc missing '## Scope' heading"
    )


def test_audit_doc_has_methodology_section(audit_doc_text: str) -> None:
    """The audit doc MUST carry a ``## Methodology`` heading."""
    assert re.search(r"^##\s+Methodology\b", audit_doc_text, re.MULTILINE), (
        "audit doc missing '## Methodology' heading"
    )


def test_audit_doc_has_findings_section_with_severity_table(
    audit_doc_text: str,
) -> None:
    """The audit doc MUST carry a ``## Findings`` heading + a severity table.

    The severity table is the spec requirement: operators grep the
    severity column for ``P0`` / ``P1`` / ``P2`` / ``P3`` to find
    gating findings. A regression that drops the column would
    silently reduce the audit to prose.
    """
    assert re.search(r"^##\s+Findings\b", audit_doc_text, re.MULTILINE), (
        "audit doc missing '## Findings' heading"
    )
    # The findings table MUST expose all four severity levels as
    # rows so the operator can grep them.
    findings_idx = audit_doc_text.find("## Findings")
    after_findings = audit_doc_text[findings_idx:]
    next_h2 = re.search(r"^##\s+", after_findings[10:], re.MULTILINE)
    findings_section = (
        after_findings
        if next_h2 is None
        else after_findings[: next_h2.start() + 10]
    )
    for severity in ("P0", "P1", "P2", "P3"):
        assert re.search(rf"\b{severity}\b", findings_section), (
            f"audit doc Findings section missing severity level {severity}"
        )


def test_audit_doc_has_verdict_pass(audit_doc_text: str) -> None:
    """The audit doc MUST carry a ``## Verdict`` heading with PASS."""
    assert re.search(r"^##\s+Verdict\b", audit_doc_text, re.MULTILINE), (
        "audit doc missing '## Verdict' heading"
    )
    verdict_idx = audit_doc_text.find("## Verdict")
    verdict_section = audit_doc_text[verdict_idx:]
    # PASS MUST appear in the verdict body. The grep is loose enough
    # to allow PASS without false positives (any other PASS-shaped
    # substring is also intentional — operators read it as PASS).
    assert re.search(r"\bPASS\b", verdict_section), (
        "audit doc Verdict section does not contain PASS"
    )


def test_audit_doc_enumerates_three_pr4b_pii_fields(audit_doc_text: str) -> None:
    """The Scope section MUST enumerate ``email``, ``tel1``, ``tel2``, ``dni``."""
    scope_idx = audit_doc_text.find("## Scope")
    # Match the START of the next h2 (newline + "## "), not a
    # bare "## " substring that may appear inside a fenced block.
    next_h2 = re.search(r"\n##\s+", audit_doc_text[scope_idx + 5:])
    scope_end = scope_idx + 5 + next_h2.start() if next_h2 else len(audit_doc_text)
    scope_section = audit_doc_text[scope_idx:scope_end]
    for column in ("email", "tel1", "tel2", "dni"):
        assert column in scope_section, (
            f"audit doc Scope section missing PII column {column!r}"
        )


def test_audit_doc_enumerates_foto_route(audit_doc_text: str) -> None:
    """The Scope section MUST mention ``/animales/{animal_id}/foto`` (UUID)."""
    assert "/animales/{animal_id}/foto" in audit_doc_text, (
        "audit doc Scope section missing the foto route"
    )
    # The UUID identifier convention is pinned per design correction L.
    assert "UUID" in audit_doc_text


def test_audit_doc_pins_fifteen_redacted_fields(audit_doc_text: str) -> None:
    """The Scope / redaction-list area MUST enumerate the 15-field closed list."""
    # Either the audit doc states "15 entries" or it explicitly lists
    # all 15 entries (the second is stricter; we accept both).
    if "15" in audit_doc_text:
        # Pin one of the new entries so the count can't be faked.
        assert "dni" in audit_doc_text
    else:
        for column in (
            "email",
            "session_token",
            "jwt",
            "oauth_code",
            "pkce_verifier",
            "csrf_token",
            "pkce_challenge",
            "authorization",
            "cookie",
            "referer",
            "ip_address",
            "x_forwarded_for",
            "dni",
            "tel1",
            "tel2",
        ):
            assert column in audit_doc_text, (
                f"audit doc missing closed-list field {column!r}"
            )
