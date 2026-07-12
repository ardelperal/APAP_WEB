"""Repository-level test: every operator-facing migration runbook reference resolves.

Per PR3 verification remediation C-3 (2026-07-11), this test
captures the contract that every CLI / legacy reader / ``pyproject.toml``
reference to ``docs/runbooks/<file>.md`` points to a file that
actually exists on disk. The contract is enforced at test-time so a
drift between code / config and documentation surfaces as a failed
test instead of a dead link in a production error message.

Scope:

- ``migration.cli.MIGRATION_RUNBOOK_REF`` — the apply runbook
  constant used in operator-facing CLI error output. The CLI emits
  ``runbook=<ref>`` for every typed exception; a missing runbook
  file surfaces as a dead link in production.
- ``migration.dysflow_client`` — the pyodbc executor's module
  docstring + user-visible error messages name the operator runbook
  for closing Access manually and troubleshooting the executor.
  These are operator-facing because they appear in
  ``NotImplementedError`` messages at runtime.
- ``pyproject.toml`` — the dependency comment for ``pyodbc`` names
  the runbook the operator consults when the executor raises
  ``LegacyReaderError`` ("Without it, the CLI exits 5 with a
  clear install hint in the runbook …"). A stale reference
  here surfaces as a dead link in the comment that the operator
  follows after a real install failure.

Hard Rules honoured (web-tdd-philosophy):

- Rule 1 (fixture gate): the test is hermetic; no fixtures.
- Rule 4 (no humo): assertions pin the resolved path / status, not
  absence-of-error.
- Rule 6 (refactor-safety): tests assert against the constant
  value + the resolved filesystem path, not internal call sites.

Three paths per slice (web-tdd-philosophy Rule 5):

- happy: every operator-facing reference resolves to an authored
  ``docs/runbooks/<file>.md`` file with at least the AGENTS.md §13
  required sections.
- sad: a missing file surfaces as a failed test (the operator sees
  the test failure at PR-review time, not a dead link in production).
- edge: cross-cutting — the CLI constant and the dysflow_client
  references point to the SAME canonical runbook (no operator
  confusion across two divergent references).

AGENTS.md §13 required sections (verified per resolved runbook):

- ``## When to trigger``
- ``## Pre-deploy checklist``
- ``## Deploy steps``
- ``## Verification``
- ``## Rollback``
"""

from __future__ import annotations

import re
from pathlib import Path

from migration import cli as cli_mod
from migration import dysflow_client as dysflow_mod

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_RUNBOOKS_DIR = REPO_ROOT / "docs" / "runbooks"
AGENTS_SECTION_13_HEADINGS: tuple[str, ...] = (
    "## When to trigger",
    "## Pre-deploy checklist",
    "## Deploy steps",
    "## Verification",
    "## Rollback",
)
# Match repo-relative ``docs/runbooks/<name>.md`` references; capture
# the full path (no scheme, no URL).
_RUNBOOK_REF_RE = re.compile(r"docs/runbooks/[A-Za-z0-9_./-]+\.md")


def _resolve_runbook(path_value: str) -> Path:
    """Resolve a repo-relative ``docs/runbooks/<name>.md`` to absolute."""
    return (REPO_ROOT / path_value).resolve()


def _missing_required_headings(text: str) -> list[str]:
    """Return the AGENTS §13 headings that are NOT present in ``text``."""
    return [h for h in AGENTS_SECTION_13_HEADINGS if h not in text]


def _discover_dysflow_runbook_refs() -> list[str]:
    """Return the sorted, deduplicated runbook paths named in dysflow_client.py."""
    src = Path(dysflow_mod.__file__).read_text(encoding="utf-8")
    return sorted(set(_RUNBOOK_REF_RE.findall(src)))


# --------------------------------------------------------------------------
# CLI constant
# --------------------------------------------------------------------------


class TestCliRunbookReference:
    """``MIGRATION_RUNBOOK_REF`` resolves to an authored file with §13 sections."""

    def test_cli_runbook_reference_resolves_to_existing_file(self) -> None:
        ref = cli_mod.MIGRATION_RUNBOOK_REF
        resolved = _resolve_runbook(ref)
        assert resolved.exists(), (
            f"CLI runbook reference {ref!r} does not resolve to an "
            f"existing file on disk: {resolved}"
        )
        assert resolved.is_file(), (
            f"CLI runbook reference {ref!r} is not a regular file: {resolved}"
        )

    def test_cli_runbook_reference_points_to_docs_runbooks(self) -> None:
        """The CLI constant lives under ``docs/runbooks/`` (the operator's docs tree)."""
        ref = cli_mod.MIGRATION_RUNBOOK_REF
        assert ref.startswith("docs/runbooks/"), (
            f"MIGRATION_RUNBOOK_REF must live under docs/runbooks/; got {ref!r}"
        )
        assert ref.endswith(".md"), (
            f"MIGRATION_RUNBOOK_REF must be a Markdown file; got {ref!r}"
        )

    def test_cli_runbook_file_has_required_agents_section_13_headings(self) -> None:
        """The resolved runbook has every AGENTS §13 heading (operator contract)."""
        ref = cli_mod.MIGRATION_RUNBOOK_REF
        resolved = _resolve_runbook(ref)
        text = resolved.read_text(encoding="utf-8")
        missing = _missing_required_headings(text)
        assert not missing, (
            f"CLI runbook {ref!r} is missing required AGENTS §13 "
            f"headings: {missing!r}"
        )


# --------------------------------------------------------------------------
# Legacy reader (pyodbc executor)
# --------------------------------------------------------------------------


class TestDysflowRunbookReferences:
    """Every runbook path in ``migration/dysflow_client.py`` resolves to an authored file."""

    def test_dysflow_client_documents_at_least_one_runbook(self) -> None:
        refs = _discover_dysflow_runbook_refs()
        assert refs, (
            "expected at least one docs/runbooks/... reference in "
            "migration/dysflow_client.py (operator-facing docstring "
            "or error message)"
        )

    def test_dysflow_client_runbook_refs_resolve(self) -> None:
        refs = _discover_dysflow_runbook_refs()
        for ref in refs:
            resolved = _resolve_runbook(ref)
            assert resolved.exists(), (
                f"dysflow_client.py runbook reference {ref!r} does "
                f"not resolve to an existing file: {resolved}"
            )
            assert resolved.is_file(), (
                f"dysflow_client.py runbook reference {ref!r} is not "
                f"a regular file: {resolved}"
            )

    def test_dysflow_client_runbook_refs_have_agents_section_13(self) -> None:
        refs = _discover_dysflow_runbook_refs()
        for ref in refs:
            resolved = _resolve_runbook(ref)
            text = resolved.read_text(encoding="utf-8")
            missing = _missing_required_headings(text)
            assert not missing, (
                f"dysflow_client.py runbook {ref!r} is missing required "
                f"AGENTS §13 headings: {missing!r}"
            )


# --------------------------------------------------------------------------
# Cross-cutting consistency
# --------------------------------------------------------------------------


class TestRunbookReferenceConsistency:
    """CLI constant + dysflow_client references point to the SAME canonical runbook.

    Divergent references create operator confusion: the CLI error
    stream points to one runbook while the legacy executor's error
    stream points to another. The contract is one canonical operator
    runbook for the apply pipeline.
    """

    def test_cli_and_dysflow_references_are_consistent(self) -> None:
        cli_ref = cli_mod.MIGRATION_RUNBOOK_REF
        dysflow_refs = _discover_dysflow_runbook_refs()
        for ref in dysflow_refs:
            assert ref == cli_ref, (
                f"dysflow_client.py reference {ref!r} disagrees with "
                f"the CLI constant {cli_ref!r}; both must point to the "
                f"same canonical operator runbook"
            )

    def test_all_runbook_refs_live_under_docs_runbooks(self) -> None:
        """Every operator-facing reference is under ``docs/runbooks/``.

        No reference should escape the operator docs tree (e.g.
        ``README.md`` at the repo root, an audit doc under
        ``docs/audits/``, or a wiki link).
        """
        all_refs = [cli_mod.MIGRATION_RUNBOOK_REF] + _discover_dysflow_runbook_refs()
        for ref in all_refs:
            assert ref.startswith("docs/runbooks/"), (
                f"operator runbook reference {ref!r} must live under "
                f"docs/runbooks/"
            )
            assert ref.endswith(".md"), (
                f"operator runbook reference {ref!r} must be Markdown"
            )


# --------------------------------------------------------------------------
# pyproject.toml
# --------------------------------------------------------------------------


PYPROJECT_TOML = REPO_ROOT / "pyproject.toml"


def _discover_pyproject_runbook_refs() -> list[str]:
    """Return the sorted, deduplicated runbook paths named in ``pyproject.toml``.

    Scans every line of the file for the ``docs/runbooks/<name>.md``
    pattern. The repository's own runbook regex is reused so the
    capture set stays in lock-step with the other test classes.
    """
    src = PYPROJECT_TOML.read_text(encoding="utf-8")
    return sorted(set(_RUNBOOK_REF_RE.findall(src)))


class TestPyprojectRunbookReferences:
    """Every runbook path in ``pyproject.toml`` resolves to an authored file.

    The ``pyodbc`` dependency comment in ``pyproject.toml`` names the
    runbook the operator consults after a real install failure
    ("Without it, the CLI exits 5 with a clear install hint in the
    runbook …"). A stale reference here is a dead link surfaced in
    the comment that follows an install error, not a CI test, so the
    contract is captured here.
    """

    def test_pyproject_documents_at_least_one_runbook(self) -> None:
        refs = _discover_pyproject_runbook_refs()
        assert refs, (
            "expected at least one docs/runbooks/... reference in "
            "pyproject.toml (the pyodbc install-hint comment names "
            "the operator runbook)"
        )

    def test_pyproject_runbook_refs_resolve(self) -> None:
        refs = _discover_pyproject_runbook_refs()
        for ref in refs:
            resolved = _resolve_runbook(ref)
            assert resolved.exists(), (
                f"pyproject.toml runbook reference {ref!r} does not "
                f"resolve to an existing file: {resolved}"
            )
            assert resolved.is_file(), (
                f"pyproject.toml runbook reference {ref!r} is not a "
                f"regular file: {resolved}"
            )

    def test_pyproject_runbook_refs_have_agents_section_13(self) -> None:
        """Every runbook referenced from ``pyproject.toml`` has the AGENTS §13 contract.

        A reference surfaced to the operator (via the pyodbc
        install-hint comment) MUST satisfy the same AGENTS §13
        contract as the CLI constant + dysflow_client references.
        Otherwise the operator lands on a stub file and the
        install flow breaks.
        """
        refs = _discover_pyproject_runbook_refs()
        for ref in refs:
            resolved = _resolve_runbook(ref)
            text = resolved.read_text(encoding="utf-8")
            missing = _missing_required_headings(text)
            assert not missing, (
                f"pyproject.toml runbook {ref!r} is missing required "
                f"AGENTS §13 headings: {missing!r}"
            )

    def test_pyproject_and_cli_reference_same_canonical_runbook(self) -> None:
        """``pyproject.toml`` and the CLI constant point to the SAME runbook.

        The pyodbc install-hint comment and the CLI error output
        both point the operator at the same operator runbook. If
        they diverge, the operator follows a comment, lands on
        a different runbook, and loses the canonical pre-flight /
        rollback / escalation chain.
        """
        refs = _discover_pyproject_runbook_refs()
        cli_ref = cli_mod.MIGRATION_RUNBOOK_REF
        for ref in refs:
            assert ref == cli_ref, (
                f"pyproject.toml reference {ref!r} disagrees with "
                f"the CLI constant {cli_ref!r}; both must point to the "
                f"same canonical operator runbook"
            )
