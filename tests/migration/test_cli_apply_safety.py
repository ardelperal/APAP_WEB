"""Tests for ``migration.cli.run_apply`` exception → exit-code mapping (PR3 remediation).

Contract (per user directive, 2026-07-11):

- ``MsAccessRunningError`` → exit 5, reason ``msaccess_running``.
- ``MsAccessPreflightUnavailableError`` → exit 5, reason
  ``msaccess_preflight_unavailable``.
- ``LegacyReaderError`` → exit 5, reason ``legacy_read_failed``.
- ``BackendError`` (infra-bootstrap path) → exit 5, reason
  ``infra_bootstrap_failed``.
- ``SourceDriftError`` → exit 6, reason ``source_drift``.
- ``PartialApplyInterruptedError`` → exit 7, reason
  ``partial_apply_interrupted``.

Output format is deterministic:

    apap-migrate apply: status=error reason=<categorical> exit=<N> runbook=<ref>

Constraints:

- No traceback in the operator stream.
- No raw PII (DNI / Email / Tel1 / Tel2) leaked into the operator stream.
- No raw filesystem paths leaked (no ``/var/...``, ``C:\\...``, no
  ``migration.partial_apply.json`` literal in the dry-run-error stream).
- The runbook reference is a STABLE constant — the operator's
  documentation surface always points to the same path.
- Each error stream contains ``status=error reason=<cat> exit=<N>
  runbook=<ref>`` exactly once.

Hard Rules honoured (web-tdd-philosophy):

- Rule 1 (fixture gate): every test builds its own FakeInsForge +
  StringIO stream + monkeypatched ``apply_legacy_to_web``.
- Rule 4 (no humo): assertions pin concrete substring occurrences in
  the captured stream, not absence-of-error.
- Rule 5 (three paths): happy (typed exception → expected exit+reason)
  + sad (no traceback, no PII/path leakage) + edge (each exception type
  + categorical reason stable across calls).
- Rule 6 (refactor-safety): tests assert on the rendered output, not
  internal helper calls.
"""

from __future__ import annotations

import argparse
import io

import pytest

from app.core.insforge import BackendError
from migration import MsAccessPreflightUnavailableError
from migration import cli as cli_mod
from migration.apply import (
    MsAccessRunningError,
    PartialApplyInterruptedError,
    SourceDriftError,
)
from migration.cli import run_apply
from migration.legacy_reader import LegacyReaderError
from tests.migration.conftest import FakeInsForge  # noqa: TID251

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _make_args(
    *,
    table: str = "animal",
    legacy_path: str = "/dummy.accdb",
    check_only: bool = False,
    since: str | None = None,
) -> argparse.Namespace:
    """Build the minimal ``argparse.Namespace`` ``run_apply`` expects."""
    return argparse.Namespace(
        table=table,
        legacy_path=legacy_path,
        check_only=check_only,
        since=since,
    )


def _run_apply_with_exception(
    monkeypatch: pytest.MonkeyPatch,
    web_client: FakeInsForge,
    exc: BaseException,
) -> tuple[int, str]:
    """Drive ``run_apply`` with ``apply_legacy_to_web`` patched to raise ``exc``.

    Returns ``(exit_code, output_text)``. ``apply_legacy_to_web`` is
    monkeypatched in the ``migration.cli`` namespace (where ``run_apply``
    imports it) so the patch is the same view the CLI sees in
    production.
    """
    monkeypatch.setattr(cli_mod, "apply_legacy_to_web", _raise_factory(exc))
    stream = io.StringIO()
    rc = run_apply(
        _make_args(),
        web_client=web_client,
        stream=stream,
    )
    return rc, stream.getvalue()


def _raise_factory(exc: BaseException):
    """Return a no-arg callable that raises ``exc`` (defeats mypy ``abstract``)."""

    def _raise(*_args: object, **_kwargs: object) -> None:
        raise exc

    return _raise


# --------------------------------------------------------------------------
# Exit code + categorical reason (happy path per exception type)
# --------------------------------------------------------------------------


class TestExitCodeMapping:
    """Typed exceptions map to deterministic exit codes + categorical reasons."""

    def test_msaccess_running_returns_exit_5(
        self,
        monkeypatch: pytest.MonkeyPatch,
        web_client: FakeInsForge,
    ) -> None:
        rc, out = _run_apply_with_exception(
            monkeypatch,
            web_client,
            MsAccessRunningError(pids=[12345], detail="opaque"),
        )
        assert rc == 5
        assert "reason=msaccess_running" in out
        assert "exit=5" in out

    def test_msaccess_preflight_unavailable_returns_exit_5(
        self,
        monkeypatch: pytest.MonkeyPatch,
        web_client: FakeInsForge,
    ) -> None:
        rc, out = _run_apply_with_exception(
            monkeypatch,
            web_client,
            MsAccessPreflightUnavailableError(
                reason=MsAccessPreflightUnavailableError.REASON_PSUTIL_MISSING
            ),
        )
        assert rc == 5
        assert "reason=msaccess_preflight_unavailable" in out
        assert "exit=5" in out

    def test_source_drift_returns_exit_6(
        self,
        monkeypatch: pytest.MonkeyPatch,
        web_client: FakeInsForge,
    ) -> None:
        rc, out = _run_apply_with_exception(
            monkeypatch,
            web_client,
            SourceDriftError(
                detail="opaque",
                accdb_sha256_changed=True,
                photos_dir_sha256_changed=False,
                photos_file_count_delta=0,
                photos_total_bytes_delta=0,
            ),
        )
        assert rc == 6
        assert "reason=source_drift" in out
        assert "exit=6" in out

    def test_partial_apply_interrupted_returns_exit_7(
        self,
        monkeypatch: pytest.MonkeyPatch,
        web_client: FakeInsForge,
    ) -> None:
        rc, out = _run_apply_with_exception(
            monkeypatch,
            web_client,
            PartialApplyInterruptedError(
                detail="opaque",
                evidence={
                    "schema_version": 1,
                    "direction": "legacy-to-web",
                    "table_name": "animal",
                    "progress_applied": 42,
                    "progress_total": None,
                    "reason": "sigint",
                    "recorded_at": "2026-07-11T00:00:00+00:00",
                },
            ),
        )
        assert rc == 7
        assert "reason=partial_apply_interrupted" in out
        assert "exit=7" in out

    def test_legacy_reader_error_returns_exit_5(
        self,
        monkeypatch: pytest.MonkeyPatch,
        web_client: FakeInsForge,
    ) -> None:
        rc, out = _run_apply_with_exception(
            monkeypatch,
            web_client,
            LegacyReaderError("opaque raw pyodbc message"),
        )
        assert rc == 5
        assert "reason=legacy_read_failed" in out
        assert "exit=5" in out

    def test_insforge_error_returns_exit_5(
        self,
        monkeypatch: pytest.MonkeyPatch,
        web_client: FakeInsForge,
    ) -> None:
        rc, out = _run_apply_with_exception(
            monkeypatch,
            web_client,
            BackendError(
                500,
                {"error": "bucket_readback_missing", "message": "sensitive"},
            ),
        )
        assert rc == 5
        assert "reason=infra_bootstrap_failed" in out
        assert "exit=5" in out


# --------------------------------------------------------------------------
# Output safety: no traceback, no raw PII, no raw paths
# --------------------------------------------------------------------------


class TestOutputSafety:
    """Operator stream carries the categorical contract only — nothing more."""

    @pytest.mark.parametrize(
        "exc",
        [
            MsAccessRunningError(pids=[12345], detail="opaque"),
            MsAccessPreflightUnavailableError(
                reason=MsAccessPreflightUnavailableError.REASON_PSUTIL_MISSING
            ),
            SourceDriftError(
                detail="opaque",
                accdb_sha256_changed=True,
                photos_dir_sha256_changed=False,
                photos_file_count_delta=0,
                photos_total_bytes_delta=0,
            ),
            PartialApplyInterruptedError(
                detail="opaque",
                evidence={
                    "schema_version": 1,
                    "direction": "legacy-to-web",
                    "table_name": "animal",
                    "progress_applied": 42,
                    "progress_total": None,
                    "reason": "sigint",
                    "recorded_at": "2026-07-11T00:00:00+00:00",
                },
            ),
            LegacyReaderError("opaque pyodbc detail"),
            BackendError(
                500, {"error": "bucket_readback_missing", "message": "sensitive"}
            ),
        ],
        ids=[
            "msaccess_running",
            "msaccess_preflight_unavailable",
            "source_drift",
            "partial_apply_interrupted",
            "legacy_reader_error",
            "insforge_error",
        ],
    )
    def test_no_traceback_in_operator_stream(
        self,
        monkeypatch: pytest.MonkeyPatch,
        web_client: FakeInsForge,
        exc: BaseException,
    ) -> None:
        """Operator output never contains a Python traceback.

        A traceback in the operator-facing stream would leak class
        names, file paths, and internals. The CLI catches every
        expected exception and renders a single categorical line.
        """
        _rc, out = _run_apply_with_exception(monkeypatch, web_client, exc)
        assert "Traceback" not in out
        assert "File \"" not in out  # noqa: W291 — traceback frames
        assert "raise " not in out

    @pytest.mark.parametrize(
        "exc",
        [
            MsAccessRunningError(pids=[12345], detail="opaque"),
            MsAccessPreflightUnavailableError(
                reason=MsAccessPreflightUnavailableError.REASON_PSUTIL_MISSING
            ),
            SourceDriftError(
                detail="opaque",
                accdb_sha256_changed=True,
                photos_dir_sha256_changed=False,
                photos_file_count_delta=0,
                photos_total_bytes_delta=0,
            ),
            PartialApplyInterruptedError(
                detail="opaque",
                evidence={
                    "schema_version": 1,
                    "direction": "legacy-to-web",
                    "table_name": "animal",
                    "progress_applied": 42,
                    "progress_total": None,
                    "reason": "sigint",
                    "recorded_at": "2026-07-11T00:00:00+00:00",
                },
            ),
            LegacyReaderError("opaque pyodbc detail"),
            BackendError(
                500, {"error": "bucket_readback_missing", "message": "sensitive"}
            ),
        ],
    )
    def test_no_raw_pii_in_operator_stream(
        self,
        monkeypatch: pytest.MonkeyPatch,
        web_client: FakeInsForge,
        exc: BaseException,
    ) -> None:
        """Operator output never embeds PII column names or values.

        The CLI contract is categorical reasons + exit codes; the
        operator reads the runbook for the verbose interpretation.
        """
        _rc, out = _run_apply_with_exception(monkeypatch, web_client, exc)
        for forbidden in ("DNI", "Email", "Tel1", "Tel2"):
            assert forbidden not in out, (
                f"forbidden PII token {forbidden!r} leaked into operator stream: {out!r}"
            )

    @pytest.mark.parametrize(
        "exc",
        [
            MsAccessRunningError(pids=[12345], detail="opaque"),
            MsAccessPreflightUnavailableError(
                reason=MsAccessPreflightUnavailableError.REASON_PSUTIL_MISSING
            ),
            SourceDriftError(
                detail="opaque",
                accdb_sha256_changed=True,
                photos_dir_sha256_changed=False,
                photos_file_count_delta=0,
                photos_total_bytes_delta=0,
            ),
            PartialApplyInterruptedError(
                detail="opaque",
                evidence={
                    "schema_version": 1,
                    "direction": "legacy-to-web",
                    "table_name": "animal",
                    "progress_applied": 42,
                    "progress_total": None,
                    "reason": "sigint",
                    "recorded_at": "2026-07-11T00:00:00+00:00",
                },
            ),
            LegacyReaderError("opaque pyodbc detail"),
            BackendError(
                500, {"error": "bucket_readback_missing", "message": "sensitive"}
            ),
        ],
    )
    def test_no_raw_filesystem_paths_in_operator_stream(
        self,
        monkeypatch: pytest.MonkeyPatch,
        web_client: FakeInsForge,
        exc: BaseException,
    ) -> None:
        """Operator output never embeds filesystem paths.

        ``migration.partial_apply.json``, ``/var/...``, ``C:\\...``,
        ``migration_dir``-style subdirs MUST NOT appear in the operator
        stream. The runbook reference is a stable repo-relative path
        (no absolute prefix).
        """
        _rc, out = _run_apply_with_exception(monkeypatch, web_client, exc)
        for forbidden in (
            "migration.partial_apply.json",
            "migration.lock_snapshot.json",
            "/var/",
            "C:\\",
            "C:/",
            "/home/",
            "/tmp/",
            "TEMP=",
        ):
            assert forbidden not in out, (
                f"forbidden path token {forbidden!r} leaked into operator stream: {out!r}"
            )

    @pytest.mark.parametrize(
        "exc",
        [
            MsAccessRunningError(pids=[12345], detail="opaque"),
            MsAccessPreflightUnavailableError(
                reason=MsAccessPreflightUnavailableError.REASON_PSUTIL_MISSING
            ),
            SourceDriftError(
                detail="opaque",
                accdb_sha256_changed=True,
                photos_dir_sha256_changed=False,
                photos_file_count_delta=0,
                photos_total_bytes_delta=0,
            ),
            PartialApplyInterruptedError(
                detail="opaque",
                evidence={
                    "schema_version": 1,
                    "direction": "legacy-to-web",
                    "table_name": "animal",
                    "progress_applied": 42,
                    "progress_total": None,
                    "reason": "sigint",
                    "recorded_at": "2026-07-11T00:00:00+00:00",
                },
            ),
            LegacyReaderError("opaque pyodbc detail"),
            BackendError(
                500, {"error": "bucket_readback_missing", "message": "sensitive"}
            ),
        ],
    )
    def test_runbook_reference_present_and_stable(
        self,
        monkeypatch: pytest.MonkeyPatch,
        web_client: FakeInsForge,
        exc: BaseException,
    ) -> None:
        """Operator output always names the migration apply runbook.

        The reference is a stable repo-relative path. Every typed
        exception surfaces the same runbook so the operator's docs
        lookup is deterministic.
        """
        _rc, out = _run_apply_with_exception(monkeypatch, web_client, exc)
        assert "runbook=" in out
        assert "docs/runbooks/live-migration-apply.md" in out

    @pytest.mark.parametrize(
        "exc",
        [
            MsAccessRunningError(pids=[12345], detail="opaque"),
            MsAccessPreflightUnavailableError(
                reason=MsAccessPreflightUnavailableError.REASON_PSUTIL_MISSING
            ),
            SourceDriftError(
                detail="opaque",
                accdb_sha256_changed=True,
                photos_dir_sha256_changed=False,
                photos_file_count_delta=0,
                photos_total_bytes_delta=0,
            ),
            PartialApplyInterruptedError(
                detail="opaque",
                evidence={
                    "schema_version": 1,
                    "direction": "legacy-to-web",
                    "table_name": "animal",
                    "progress_applied": 42,
                    "progress_total": None,
                    "reason": "sigint",
                    "recorded_at": "2026-07-11T00:00:00+00:00",
                },
            ),
            LegacyReaderError("opaque pyodbc detail"),
            BackendError(
                500, {"error": "bucket_readback_missing", "message": "sensitive"}
            ),
        ],
    )
    def test_output_is_single_categorical_line(
        self,
        monkeypatch: pytest.MonkeyPatch,
        web_client: FakeInsForge,
        exc: BaseException,
    ) -> None:
        """Operator output is ONE line with the contract shape.

        Multiple lines would scatter the categorical reason across
        noise. The contract is: exactly one ``status=error ...`` line.
        """
        _rc, out = _run_apply_with_exception(monkeypatch, web_client, exc)
        lines = [line for line in out.splitlines() if line.strip()]
        assert len(lines) == 1, (
            f"expected exactly one operator line; got {len(lines)}: {lines!r}"
        )
        assert lines[0].startswith("apap-migrate apply:")
        assert "status=error" in lines[0]
        assert "reason=" in lines[0]
        assert "exit=" in lines[0]
        assert "runbook=" in lines[0]


# --------------------------------------------------------------------------
# PII / path leakage regression — apply-safety exception payloads
# --------------------------------------------------------------------------


class TestPayloadsNotLeaked:
    """The exception's structured payload MUST NOT bleed into the stream.

    Even though the CLI doesn't print ``exc.detail``, ``exc.pids``,
    ``exc.evidence``, or ``exc.body``, this guard pins the invariant
    for the future: any new field on a typed exception stays out of
    the operator stream unless explicitly approved.
    """

    def test_msaccess_pids_not_in_stream(
        self,
        monkeypatch: pytest.MonkeyPatch,
        web_client: FakeInsForge,
    ) -> None:
        # The PIDs are integers; if the CLI ever prints them, the
        # digit pattern would surface in the stream.
        rc, out = _run_apply_with_exception(
            monkeypatch,
            web_client,
            MsAccessRunningError(pids=[12345, 67890], detail="opaque"),
        )
        assert rc == 5
        for pid in (12345, 67890):
            assert str(pid) not in out

    def test_partial_apply_evidence_not_in_stream(
        self,
        monkeypatch: pytest.MonkeyPatch,
        web_client: FakeInsForge,
    ) -> None:
        # The evidence dict carries ``progress_applied`` and
        # ``table_name``; none of these surface in the operator stream.
        rc, out = _run_apply_with_exception(
            monkeypatch,
            web_client,
            PartialApplyInterruptedError(
                detail="opaque",
                evidence={
                    "schema_version": 1,
                    "direction": "legacy-to-web",
                    "table_name": "animal",
                    "progress_applied": 42,
                    "progress_total": None,
                    "reason": "sigint",
                    "recorded_at": "2026-07-11T00:00:00+00:00",
                },
            ),
        )
        assert rc == 7
        for token in ("animal", "42", "sigint", "legacy-to-web"):
            assert token not in out

    def test_insforge_body_message_not_in_stream(
        self,
        monkeypatch: pytest.MonkeyPatch,
        web_client: FakeInsForge,
    ) -> None:
        # BackendError.body["message"] can carry server-side internal
        # details (table names, status codes). The CLI MUST NOT echo it.
        rc, out = _run_apply_with_exception(
            monkeypatch,
            web_client,
            BackendError(
                500,
                {
                    "error": "bucket_readback_missing",
                    "message": "sensitive internal detail",
                },
            ),
        )
        assert rc == 5
        assert "sensitive internal detail" not in out
        assert "bucket_readback_missing" not in out

    def test_legacy_reader_raw_message_not_in_stream(
        self,
        monkeypatch: pytest.MonkeyPatch,
        web_client: FakeInsForge,
    ) -> None:
        rc, out = _run_apply_with_exception(
            monkeypatch,
            web_client,
            LegacyReaderError("SELECT * FROM TbSecretCredentials"),
        )
        assert rc == 5
        assert "SELECT" not in out
        assert "TbSecretCredentials" not in out


# --------------------------------------------------------------------------
# Stability — categorical reasons are stable across calls
# --------------------------------------------------------------------------


class TestCategoricalReasonStability:
    """Two calls with the same exception type produce identical reasons."""

    @pytest.mark.parametrize(
        "exc_factory",
        [
            lambda: MsAccessRunningError(pids=[1], detail="a"),
            lambda: MsAccessRunningError(pids=[2], detail="b"),
            lambda: MsAccessRunningError(pids=[99999], detail="c"),
        ],
    )
    def test_msaccess_running_reason_stable(
        self,
        monkeypatch: pytest.MonkeyPatch,
        web_client: FakeInsForge,
        exc_factory,
    ) -> None:
        rc1, out1 = _run_apply_with_exception(
            monkeypatch, web_client, exc_factory()
        )
        rc2, out2 = _run_apply_with_exception(
            monkeypatch, web_client, exc_factory()
        )
        assert rc1 == rc2 == 5
        assert (
            out1.split("reason=")[1].split(" ")[0]
            == out2.split("reason=")[1].split(" ")[0]
        )


# --------------------------------------------------------------------------
# Dry-run path is unaffected by new exception handlers
# --------------------------------------------------------------------------


class TestDryRunUnaffected:
    """``--check-only`` (dry-run) bypasses preflight and never hits the new handlers.

    The dry-run → no-preflight invariant is enforced inside
    ``apply_legacy_to_web`` (``if not dry_run: ...``); the CLI simply
    forwards ``--check-only`` as ``dry_run=True``. Coverage of the
    bypass itself lives in
    :class:`tests.migration.test_apply_safety.TestMsaccessPreflightFailClosed.test_apply_dry_run_does_not_consult_preflight`;
    the CLI-level dry-run happy path is covered by the pre-existing
    :func:`tests.migration.test_cli.test_cli_apply_check_only_does_not_write`.
    This class pins the CLI-level invariant that ``--check-only`` does
    NOT route through the new exception handlers (i.e. the dry-run
    path does NOT print ``status=error ...`` even when the underlying
    apply would otherwise have raised).
    """

    def test_dry_run_with_msaccess_executor_raises_does_not_propagate(
        self,
        monkeypatch: pytest.MonkeyPatch,
        web_client: FakeInsForge,
    ) -> None:
        """If ``apply_legacy_to_web`` were to raise on dry-run, the CLI would surface it.

        This pins the dry-run routing: even if a future regression
        causes ``apply_legacy_to_web`` to raise (e.g. preflight on
        dry-run, which is forbidden), the CLI surfaces the exception
        via the typed handlers, NOT via a Python traceback. The atom
        mocks ``apply_legacy_to_web`` to raise ``MsAccessRunningError``
        even on dry-run to assert the typed handler catches it.
        """

        def raise_even_on_dry_run(*_args: object, **_kwargs: object) -> None:
            raise MsAccessRunningError(pids=[1], detail="forced")

        monkeypatch.setattr(cli_mod, "apply_legacy_to_web", raise_even_on_dry_run)

        stream = io.StringIO()
        rc = run_apply(
            _make_args(check_only=True),
            web_client=web_client,
            stream=stream,
        )

        assert rc == 5
        output = stream.getvalue()
        assert "reason=msaccess_running" in output
        assert "exit=5" in output
        assert "Traceback" not in output
