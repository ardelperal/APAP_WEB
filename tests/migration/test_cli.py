"""CLI atoms for ``migration.cli`` apply/status subcommands (issue #168).

These atoms exercise the public ``main(argv, web_client=...)`` entry
point end-to-end (HTTP-free; ``web_client`` is injected). The CLI is
the only surface operators touch from a terminal — testing the
``apply`` / ``status`` branches here guarantees the user's experience
matches the library contract.

Hard Rules honoured (web-tdd-philosophy):

- **Rule 1 (fixture gate)**: each atom builds its own ``FakeInsForge``
  and Dysflow executor (via ``apply_runner``).
- **Rule 2 (DI)**: the CLI receives ``web_client`` via injection —
  no global client lookup.
- **Rule 4 (no humo)**: asserts on the captured stdout text and the
  exit code, never "no error".
- **Rule 8 (no production mutation)**: ``web_client`` is a
  ``FakeInsForge`` and the Dysflow mock returns canned rows.
"""

from __future__ import annotations

import io
from types import SimpleNamespace

import pytest

from migration import cli as cli_mod
from migration.cli import build_parser, main
from tests.migration.conftest import FakeInsForge  # noqa: TID251

# --- 1. apply --check-only is dry-run ---------------------------------


def test_cli_apply_check_only_does_not_write(
    web_client: FakeInsForge, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``apply --check-only`` lists what WOULD be migrated, no writes.

    The operator reads the dry-run output to decide whether the real
    apply is safe. Any writes to ``animales`` or the shadow table on
    this path are a contract bug.
    """
    from migration import legacy_reader

    legacy_rows = [
        {"NCHIP": "001", "NombreAnimal": "Rex"},
        {"NCHIP": "002", "NombreAnimal": "Luna"},
    ]

    def _fake_executor(_path, _sql, _offset, _limit):
        return legacy_rows if _offset == 0 else []

    legacy_reader.set_legacy_query_executor(_fake_executor)

    stream = io.StringIO()
    rc = main(
        [
            "apply",
            "--table",
            "animal",
            "--legacy-path",
            "/dummy.accdb",
            "--check-only",
        ],
        web_client=web_client,
        stream=stream,
    )
    legacy_reader.set_legacy_query_executor(None)

    assert rc == 0
    # No writes to either the domain table or the shadow table.
    assert web_client.all_rows("animales") == []
    assert web_client.all_rows("WEB_ONLY_FEATURE_SHADOW") == []
    # The check-only listing mentions the planned actions.
    output = stream.getvalue()
    assert "would insert" in output.lower() or "INSERT" in output.upper()


# --- 2. apply --table filter ------------------------------------------


def test_cli_apply_with_table_filter(
    web_client: FakeInsForge, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--table`` narrows the apply to one spec.

    Without ``--table`` the CLI iterates ALL mappings. With it, only
    the named spec runs. The atom asserts the domain table targeted
    is exactly the one named.
    """
    from migration import legacy_reader

    def _fake_executor(_path, _sql, _offset, _limit):
        return [{"NCHIP": "001", "NombreAnimal": "Rex"}] if _offset == 0 else []

    legacy_reader.set_legacy_query_executor(_fake_executor)

    rc = main(
        ["apply", "--table", "animal", "--legacy-path", "/dummy.accdb"],
        web_client=web_client,
        stream=io.StringIO(),
    )
    legacy_reader.set_legacy_query_executor(None)

    assert rc == 0
    # animales was targeted, NOT voluntarios.
    assert len(web_client.all_rows("animales")) == 1
    assert web_client.all_rows("voluntarios") == []


# --- 3. apply --since filter ------------------------------------------


def test_cli_apply_with_since_filter(
    web_client: FakeInsForge, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--since`` validates the ISO-8601 timestamp before any I/O.

    A bad timestamp exits 2 with a usage error, never touching the DB.
    The happy path (a valid ISO timestamp) runs to completion.
    """
    # --- happy path ---
    from migration import legacy_reader

    legacy_reader.set_legacy_query_executor(
        lambda _path, _sql, _offset, _limit: [
            {"NCHIP": "001", "NombreAnimal": "Rex"}
        ]
        if _offset == 0
        else []
    )
    rc = main(
        [
            "apply",
            "--table",
            "animal",
            "--legacy-path",
            "/dummy.accdb",
            "--since",
            "2026-01-01T00:00:00+00:00",
        ],
        web_client=web_client,
        stream=io.StringIO(),
    )
    legacy_reader.set_legacy_query_executor(None)
    assert rc == 0
    assert len(web_client.all_rows("animales")) == 1

    # --- sad path ---
    bad = io.StringIO()
    rc_bad = main(
        [
            "apply",
            "--table",
            "animal",
            "--legacy-path",
            "/dummy.accdb",
            "--since",
            "not-an-iso-timestamp",
        ],
        web_client=web_client,
        stream=bad,
    )
    assert rc_bad == 2
    # The error mentions the bad value so the operator can fix it.
    assert "not-an-iso-timestamp" in bad.getvalue() or "iso" in bad.getvalue().lower()


# --- 4. status per-table counts ---------------------------------------


def test_cli_status_shows_per_table_counts(
    web_client: FakeInsForge,
) -> None:
    """``status`` prints legacy/web counts per table.

    The CLI doesn't need a Dysflow executor on this path — it's a
    read-only snapshot of the web DB (legacy counts are returned by
    the Dysflow executor if available, else reported as ``unknown``).
    """
    web_client.seed(
        "animales",
        [
            {"nchip": "001"},
            {"nchip": "002"},
            {"nchip": "003"},
        ],
    )

    stream = io.StringIO()
    rc = main(["status"], web_client=web_client, stream=stream)

    assert rc == 0
    output = stream.getvalue()
    # The output table mentions the table name and a count.
    assert "animal" in output.lower()
    assert "3" in output  # 3 animales seeded


# --- 5. reconcile still works (backward compat) -----------------------


def test_cli_reconcile_still_works(web_client: FakeInsForge) -> None:
    """``reconcile`` (the pre-existing subcommand) must not regress.

    Issue #168 extends the CLI but does NOT replace it. A future
    refactor must not break the ``reconcile --check-only`` surface
    that PR-5/6 already shipped.
    """
    stream = io.StringIO()
    rc = main(
        ["reconcile", "--check-only"],
        web_client=web_client,
        stream=stream,
    )
    # Exit 0 even with no shadow rows to review.
    assert rc == 0
    # The parser surface still includes ``reconcile`` + the new ones.
    parser = build_parser()
    help_text = parser.format_help()
    assert "reconcile" in help_text
    assert "apply" in help_text
    assert "status" in help_text


def test_cli_main_builds_and_closes_client_when_not_injected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production CLI path builds and closes its own InsForge client.

    Tests usually inject ``web_client`` for hermetic assertions, but
    ``python -m migration status`` must be usable by an operator without
    passing a test fake. This atom patches the constructor and settings
    provider so no network or production backend is touched.
    """

    built: list[FakeInsForge] = []

    class ClosingFakeInsForge(FakeInsForge):
        def __init__(self, base_url: str, service_key: str) -> None:
            super().__init__()
            self.base_url = base_url
            self.service_key = service_key
            self.closed = False
            self.seed("animales", [{"nchip": "001"}])
            built.append(self)

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: SimpleNamespace(
            insforge_url="https://example.insforge.app",
            insforge_service_key="ik_test",
        ),
    )
    monkeypatch.setattr(cli_mod, "InsForgeClient", ClosingFakeInsForge)

    stream = io.StringIO()
    rc = main(["status", "--table", "animal"], stream=stream)

    assert rc == 0
    assert "web_count=1" in stream.getvalue()
    assert len(built) == 1
    assert built[0].closed is True


# --- 6. reconcile --filter-direction (PR5) ------------------------------


class _ShadowForDirectionFilter:
    """Fake shadow state whose listing carries an ``origin_direction``
    per row. Lets the filter-direction atoms exercise the narrowing
    path without touching a real ``ShadowStateRepository``.
    """

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = list(rows)
        self.last_kwargs: dict[str, object] | None = None

    def list_needs_review(
        self,
        *,
        table_name: str | None = None,
        since: str | None = None,
        origin_direction: str | None = None,
    ) -> list[dict[str, object]]:
        self.last_kwargs = {
            "table_name": table_name,
            "since": since,
            "origin_direction": origin_direction,
        }
        rows = list(self._rows)
        if origin_direction is not None:
            rows = [r for r in rows if r.get("origin_direction") == origin_direction]
        return rows

    def update_reconciliation_status(self, **kwargs: object) -> None:  # pragma: no cover
        return None


def test_cli_reconcile_default_lists_both_directions() -> None:
    """Without ``--filter-direction``, the CLI passes ``None`` to the
    shadow state read (the "both" semantic) and emits every row.

    Spec scenario: PR5 WU-4 "default lists both". The CLI default is
    backward-compatible with PR4 callers — they see the same
    combined listing they always did.
    """
    shadow = _ShadowForDirectionFilter(
        rows=[
            {
                "table_name": "voluntarios",
                "legacy_pk": "alice",
                "web_pk": "web-alice",
                "web_column": "dni",
                "origin_direction": "legacy-to-web",
                "reconciliation_status": "needs_review",
                "strategy": "preserve",
                "preserved_value": "[REDACTED]",
                "derived_value": None,
                "derived_at": None,
                "last_legacy_snapshot_at": "2026-07-11T10:00:00+00:00",
                "last_reconciled_at": None,
                "review_reasons": ["dni_collision"],
            },
            {
                "table_name": "voluntarios",
                "legacy_pk": "carol",
                "web_pk": "web-carol",
                "web_column": "dni",
                "origin_direction": "web-to-legacy",
                "reconciliation_status": "needs_review",
                "strategy": "preserve",
                "preserved_value": "[REDACTED]",
                "derived_value": None,
                "derived_at": None,
                "last_legacy_snapshot_at": "2026-07-11T11:00:00+00:00",
                "last_reconciled_at": None,
                "review_reasons": ["dni_collision"],
            },
        ]
    )

    stream = io.StringIO()
    rc = main(["reconcile"], web_client=FakeInsForge(), shadow_state=shadow, stream=stream)  # type: ignore[arg-type]
    assert rc == 0
    # The shadow state read was called WITHOUT an origin_direction
    # filter (None → "both" semantics).
    assert shadow.last_kwargs is not None
    assert shadow.last_kwargs["origin_direction"] is None
    # Both rows are listed.
    output = stream.getvalue()
    assert output.count("legacy_pk=alice") == 1
    assert output.count("legacy_pk=carol") == 1
    # Each line carries the origin_direction stamp.
    assert "origin_direction=legacy-to-web" in output
    assert "origin_direction=web-to-legacy" in output


def test_cli_reconcile_filter_direction_legacy_to_web_narrows_to_forward_only() -> None:
    """``--filter-direction legacy-to-web`` narrows the listing to
    forward-direction rows only.

    Spec scenario: PR5 WU-4 "--filter-direction legacy-to-web narrows
    to forward only". In PR5 the forward path is the only producer
    of needs_review rows, so the narrowing returns all rows; the
    atom pins the CLI filter wiring so a future bug that drops the
    flag surfaces immediately.
    """
    shadow = _ShadowForDirectionFilter(
        rows=[
            {
                "table_name": "voluntarios",
                "legacy_pk": "alice",
                "web_pk": "web-alice",
                "web_column": "dni",
                "origin_direction": "legacy-to-web",
                "reconciliation_status": "needs_review",
                "strategy": "preserve",
                "preserved_value": "[REDACTED]",
                "derived_value": None,
                "derived_at": None,
                "last_legacy_snapshot_at": "2026-07-11T10:00:00+00:00",
                "last_reconciled_at": None,
                "review_reasons": ["dni_collision"],
            },
        ]
    )

    stream = io.StringIO()
    rc = main(
        ["reconcile", "--filter-direction", "legacy-to-web"],
        web_client=FakeInsForge(),
        shadow_state=shadow,  # type: ignore[arg-type]
        stream=stream,
    )
    assert rc == 0
    # The CLI forwarded the filter to the shadow state read.
    assert shadow.last_kwargs is not None
    assert shadow.last_kwargs["origin_direction"] == "legacy-to-web"
    # The forward row IS listed.
    output = stream.getvalue()
    assert "legacy_pk=alice" in output
    assert "origin_direction=legacy-to-web" in output


def test_cli_reconcile_filter_direction_web_to_legacy_returns_empty_in_pr5() -> None:
    """``--filter-direction web-to-legacy`` returns an empty listing
    in PR5 because the reverse applier (PR6) does not exist yet.

    Spec scenario: PR5 WU-4 "--filter-direction web-to-legacy narrows
    to reverse only". The atom pins the CLI surface so the operator
    gets a clean empty listing instead of an error, and the filter
    plumbing is exercised end-to-end.
    """
    shadow = _ShadowForDirectionFilter(
        rows=[
            {
                "table_name": "voluntarios",
                "legacy_pk": "alice",
                "web_pk": "web-alice",
                "web_column": "dni",
                "origin_direction": "legacy-to-web",
                "reconciliation_status": "needs_review",
                "strategy": "preserve",
                "preserved_value": "[REDACTED]",
                "derived_value": None,
                "derived_at": None,
                "last_legacy_snapshot_at": "2026-07-11T10:00:00+00:00",
                "last_reconciled_at": None,
                "review_reasons": ["dni_collision"],
            },
        ]
    )

    stream = io.StringIO()
    rc = main(
        ["reconcile", "--filter-direction", "web-to-legacy"],
        web_client=FakeInsForge(),
        shadow_state=shadow,  # type: ignore[arg-type]
        stream=stream,
    )
    # Exit 0 — empty listing is not an error condition (matches the
    # PR4 --check-only exit-0 contract).
    assert rc == 0
    # The CLI forwarded the filter to the shadow state read.
    assert shadow.last_kwargs is not None
    assert shadow.last_kwargs["origin_direction"] == "web-to-legacy"
    # No forward rows in the listing (the only row is filtered out).
    output = stream.getvalue()
    assert "legacy_pk=alice" not in output
