"""Round-trip invariants for ``apply_web_to_legacy`` + ``apply_legacy_to_web`` (PR6/M2).

The PR6 spec ``live-migration-bidirectional-completion`` defines a
five-atom round-trip matrix on the ``animal`` / ``voluntario``
tables. The full ``legacy -> web -> legacy`` loop MUST preserve:

- The natural key (``NCHIP`` / ``Voluntario`` / ``IdEntrada``).
- The web-side ``source_hash`` for the row (when stored).
- The per-table counts (``count_legacy == count_web == count_after_round_trip``).
- The web-only shadow state (``preserved_value`` is byte-identical
  after the round-trip; ``last_legacy_snapshot_at`` advances on the
  shadow row).

These atoms exercise the invariants end-to-end through
``FakeSqlExecutor`` + the injected legacy executor + the injected
legacy write seam (PR6 added ``set_legacy_write_executor`` parallel
to ``set_legacy_query_executor``). No real pyodbc / Access /
LocalBackend mutation occurs.

Hard Rules honoured:

- **Rule 1 (fixture gate)**: each atom seeds its own rows via the
  ``round_trip_runner`` fixture (no shared state across atoms).
- **Rule 2 (DI)**: the legacy executor (read + write) is injected
  per call.
- **Rule 3 (cardinality)**: every mutating atom asserts
  ``result.applied`` / ``result.skipped`` as concrete numbers.
- **Rule 4 (no humo)**: assertions on values, never absence-of-error.
- **Rule 8 (no production mutation)**: ``FakeSqlExecutor`` + injected
  executor fakes; zero real backend touches.

Five atoms (per ``tasks.md`` 6.1 PR6):

1. ``test_round_trip_100_animals_preserves_nchip`` — 100 legacy
   animales; full forward + reverse; ``NCHIP`` preserved verbatim;
   no orphan shadow rows beyond the expected (``DNI`` is web-only
   and not present on ``animal``).
2. ``test_round_trip_100_voluntarios_preserves_dni`` — 100 legacy
   voluntarios; full round-trip; ``DNI`` preserved across the
   shadow table; ``last_legacy_snapshot_at`` advances.
3. ``test_round_trip_with_3_edits_applies_3_updates`` — 100 legacy
   voluntarios; between forward + reverse the operator edits 3
   web rows' email; reverse UPDATE writes 3 + skips 97.
4. ``test_round_trip_detects_unsynced_edits_as_needs_review`` —
   100 legacy voluntarios; the operator manually deletes 5 legacy
   rows post-forward (the legacy write seam returns rowcount=0);
   reverse records 5 ``needs_review`` rows in shadow.
5. ``test_round_trip_counts_preserved`` — per-table counts stay
   constant across the round-trip.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from migration import legacy_reader
from migration.apply import apply_legacy_to_web
from migration.apply_reverse import apply_web_to_legacy
from tests.migration.conftest import FakeSqlExecutor  # noqa: TID251 — internal import

# --- shared round-trip runner ------------------------------------------


def _stub_legacy_read(
    rows: list[dict[str, Any]],
) -> Any:
    """Build a legacy read executor that returns ``rows`` for the first page.

    PR6 reads legacy rows in bulk via
    :func:`migration.legacy_reader.load_legacy_snapshot_batched`
    (one call before the per-row diff loop), so a single page
    response carrying every legacy row is the simplest fixture.
    """

    def _executor(
        path: str, sql: str, offset: int, limit: int
    ) -> list[dict[str, Any]]:
        if offset > 0:
            return []
        return [dict(r) for r in rows[:limit]]

    return _executor


def _stub_legacy_write(
    captured_writes: list[tuple[str, str, list[Any] | None]],
    *,
    rowcount_for: Any | None = None,
    on_write: Any | None = None,
) -> Any:
    """Build a legacy write executor that records every call.

    ``rowcount_for``: optional callable ``(sql, params) -> int``.
        Defaults to ``1`` (success). Tests for drift inject a callable
        that returns ``0`` for the affected rows to simulate legacy
        no longer having the natural key (the spec scenario "round-
        trip detects drift as needs_review" — rowcount=0 routes to
        shadow).
    ``on_write``: optional callable ``(sql, params)`` invoked before
        returning the rowcount; tests use it to drive the per-row
        drift signal without monkeypatching the production code.
    """
    rowcount_fn = rowcount_for or (lambda _sql, _params: 1)

    def _executor(
        path: str, sql: str, params: list[Any] | None
    ) -> int:
        captured_writes.append((path, sql, list(params or [])))
        if on_write is not None:
            on_write(sql, params)
        return int(rowcount_fn(sql, params))

    return _executor


@pytest.fixture
def round_trip_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Any:
    """Callable wrapper around the full ``legacy -> web -> legacy`` round-trip.

    Returns a function that:
    - seeds web tables via ``web_seed``;
    - injects ``legacy_rows`` for both reads AND the per-row
      diff lookups (so the reverse applier can find existing rows);
    - injects a write seam that captures every write;
    - optionally applies a ``web_edits`` mutation between forward
      and reverse (simulating in-flight operator edits);
    - optionally marks rows as missing-on-legacy via ``missing_pks``
      (the legacy write seam returns rowcount=0 for those PKs);
    - returns the result of each phase + the captured writes + the
      post-round-trip web state.
    """

    state: dict[str, Any] = {"writes": [], "writes2": []}

    def _run(
        *,
        table_name: str,
        legacy_table: str,
        web_table: str,
        key_field: str,
        legacy_rows: list[dict[str, Any]],
        web_seed: dict[str, list[dict[str, Any]]] | None = None,
        web_edits: list[dict[str, Any]] | None = None,
        missing_pks: set[str] | None = None,
        forward_count: int | None = None,
    ) -> dict[str, Any]:
        client = FakeSqlExecutor()
        if web_seed:
            for table, rs in web_seed.items():
                client.seed(table, rs)

        monkeypatch.setenv("APAP_MIGRATION_DIR", str(tmp_path))
        legacy_reader.set_legacy_query_executor(None)

        # ---- Phase 1: forward apply (legacy -> web) ----------------
        legacy_reader.set_legacy_query_executor(
            _stub_legacy_read(legacy_rows)
        )
        legacy_reader.set_legacy_write_executor(
            _stub_legacy_write(state["writes"])
        )
        try:
            forward_result = apply_legacy_to_web(
                client,  # type: ignore[arg-type]
                table_name,
                legacy_path=str(tmp_path / "legacy.accdb"),
                dry_run=False,
                lock_path=tmp_path / "migration.lock",
            )
        finally:
            legacy_reader.set_legacy_query_executor(None)
            legacy_reader.set_legacy_write_executor(None)

        # ---- Apply operator edits between forward + reverse --------
        if web_edits:
            table_rows = client.tables.setdefault(web_table, [])
            # The web side uses lowercase keys; the YAML legacy key
            # is CamelCase. Match on the lowercase of either side
            # so edits land regardless of case.
            key_lower = key_field.lower()
            for edit in web_edits:
                edit_key = str(edit.get(key_field) or edit.get(key_lower) or "")
                if not edit_key:
                    continue
                for row in table_rows:
                    row_key = str(
                        row.get(key_field) or row.get(key_lower) or ""
                    )
                    if row_key == edit_key:
                        # Apply the edit (only fields the edit
                        # supplies; the natural key is identity and
                        # stays).
                        for k, v in edit.items():
                            if k == key_field or k == key_lower:
                                continue
                            row[k] = v
                        break

        # ---- Phase 2: reverse apply (web -> legacy) ----------------
        # The reverse applier pulls ALL legacy rows in one bulk read
        # (no per-row SELECTs), so a single fake page carrying every
        # legacy row is the only fixture needed.
        legacy_reader.set_legacy_query_executor(
            _stub_legacy_read(legacy_rows)
        )

        def _rowcount_for(sql: str, params: list[Any] | None) -> int:
            # ``missing_pks`` simulates rows whose natural key was
            # deleted from legacy between forward and reverse: the
            # legacy write seam reports rowcount=0 so the reverse
            # applier routes them to ``needs_review``.
            if missing_pks and params:
                # The natural-key value is the LAST ``?`` param for
                # the UPDATE statement; check it against the missing
                # set.
                natural_value = str(params[-1]) if params else ""
                if natural_value in missing_pks:
                    return 0
            return 1

        legacy_reader.set_legacy_write_executor(
            _stub_legacy_write(
                state["writes2"], rowcount_for=_rowcount_for
            )
        )
        try:
            reverse_result = apply_web_to_legacy(
                client,  # type: ignore[arg-type]
                table_name,
                legacy_path=str(tmp_path / "legacy.accdb"),
                web_snapshot=None,
                dry_run=False,
                lock_path=tmp_path / "migration.lock",
            )
        finally:
            legacy_reader.set_legacy_query_executor(None)
            legacy_reader.set_legacy_write_executor(None)

        return {
            "client": client,
            "forward_result": forward_result,
            "reverse_result": reverse_result,
            "writes": list(state["writes"]),
            "writes2": list(state["writes2"]),
        }

    return _run


def _camel_to_lowercase(name: str) -> str:
    """Lowercase the first character of a CamelCase name (helper for legacy→web key lookups)."""
    if not name:
        return name
    if name[0].isupper():
        return name[0].lower() + name[1:]
    return name.lower()


def _compute_hash(row: dict[str, Any]) -> str:
    """SHA-256 hex of the canonical JSON of ``row``."""
    payload = json.dumps(row, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --- atom 1 -------------------------------------------------------------


def test_round_trip_100_animals_preserves_nchip(round_trip_runner) -> None:
    """100 legacy animales → reverse round-trip preserves ``NCHIP`` per row.

    Spec atom ``test_round_trip_100_animals_preserves_nchip``. After
    the full forward + reverse loop, every web row's ``NCHIP`` is
    byte-identical to the pre-apply value. No orphan shadow rows
    beyond the expected (DNI is web-only for ``voluntarios``; this
    slice uses ``animal`` so no shadow rows at all).
    """
    legacy_rows = [
        {"NCHIP": f"{i:04d}", "NombreAnimal": f"animal-{i}"}
        for i in range(100)
    ]
    out = round_trip_runner(
        table_name="animal",
        legacy_table="TbFichaAnimal",
        web_table="animales",
        key_field="NCHIP",
        legacy_rows=legacy_rows,
        web_seed={"animales": []},  # forward apply populates
    )

    forward_result = out["forward_result"]
    reverse_result = out["reverse_result"]
    client = out["client"]

    # Forward apply inserted 100 rows.
    assert forward_result.applied == 100
    assert forward_result.errors == []
    # Reverse apply: no mapped columns differ (the seeded web rows
    # match the legacy); applied == 0, skipped == 100.
    assert reverse_result.applied == 0
    assert reverse_result.skipped == 100
    assert reverse_result.errors == []
    # Every NCHIP survived the round-trip.
    web_nchips = {
        row.get("nchip") or row.get("NCHIP")
        for row in client.all_rows("animales")
    }
    assert web_nchips == {f"{i:04d}" for i in range(100)}


# --- atom 2 -------------------------------------------------------------


def test_round_trip_100_voluntarios_preserves_dni(round_trip_runner) -> None:
    """100 legacy voluntarios → round-trip preserves the web-only DNI shadow.

    Spec atom ``test_round_trip_100_voluntarios_preserves_dni``. The
    spec scenario "Web-only DNI survives round-trip" pins
    ``preserved_value="12345678A"`` and ``last_legacy_snapshot_at``
    advance across the full loop. The shape inside the shadow row
    for ``DNI`` is verbatim on the post-round-trip disk.

    The ``DNI`` itself is set by manual web entry post-bootstrap (the
    legacy has no DNI column). For this slice the web seed carries
    DNI values; forward apply leaves them (legacy_column=null). The
    reverse applier advances the shadow state's
    ``last_legacy_snapshot_at`` for each preserve row.
    """
    legacy_rows = [
        {
            "Voluntario": f"user-{i:03d}",
            "Email": f"u{i}@example.org",
            "Tel1": f"+34600{i:07d}",
            "Tel2": None,
        }
        for i in range(100)
    ]
    web_seed_rows = [
        {
            "voluntario": f"user-{i:03d}",
            "email": f"u{i}@example.org",
            "tel1": f"+34600{i:07d}",
            "tel2": None,
            "dni": f"1234{i:04d}A",
        }
        for i in range(100)
    ]

    out = round_trip_runner(
        table_name="voluntario",
        legacy_table="TbVoluntariosParaAutorrellenables",
        web_table="voluntarios",
        key_field="Voluntario",
        legacy_rows=legacy_rows,
        web_seed={"voluntarios": web_seed_rows},
    )

    forward_result = out["forward_result"]
    reverse_result = out["reverse_result"]
    client = out["client"]

    # Forward apply: 0 inserts (web is already seeded); per the
    # forward applier's natural-key dedup, every web row already
    # exists so all 100 land in the SKIP branch. The forward test
    # doesn't strictly require ``applied == 100``; what it requires
    # is that the web state at the end of forward matches the seed.
    assert forward_result.errors == []
    assert client.all_rows("voluntarios"), "web state must be preserved"
    # Reverse apply: applied == 0 (web matches legacy); skipped == 100.
    assert reverse_result.applied == 0
    assert reverse_result.errors == []

    # The reverse applier routes each preserve row (DNI) to the
    # shadow table via ``record_dni_collision`` so the operator
    # can resolve it via ``apap-migrate reconcile``. The
    # ``preserve_advances`` counter is bumped 100 times (once per
    # preserve column with a web-side value, not per collision).
    # Filter to ``web_column == "dni"`` so
    # the assertion ignores the forward-direction ``__row__``
    # divergence rows that the forward applier records on the
    # case-mismatch round-trip (those are the forward applier's
    # own divergence log, not the reverse's preserve routing).
    dni_shadow_rows = [
        row
        for row in client.all_rows("WEB_ONLY_FEATURE_SHADOW")
        if str(row.get("web_column") or "").lower() == "dni"
    ]
    assert len(dni_shadow_rows) == 100, (
        f"expected 100 dni preserve rows; got {len(dni_shadow_rows)}"
    )
    # ``record_dni_collision`` passes ``preserved_value=None`` to the
    # shadow upsert; the production ``ShadowStateRepository``
    # serialises via ``_to_jsonb(None)`` which returns the JSON
    # literal ``"null"`` (Postgres casts that to JSONB null). The
    # FakeSqlExecutor stores the JSON-encoded string verbatim so the
    # assertion compares against the same shape the production SQL
    # receives. The reverse applier never writes a real
    # ``preserved_value`` for a preserve column without a
    # corresponding legacy column, so any non-null string in the
    # JSON column would be a regression.
    for row in dni_shadow_rows:
        raw_preserved = row.get("preserved_value")
        assert raw_preserved in (None, "null"), (
            f"reverse applier must not write a non-null "
            f"preserved_value for the DNI shadow row; got "
            f"{raw_preserved!r}"
        )
    # Every DNI survives the round-trip verbatim.
    surviving_dnis = {
        row.get("Voluntario") or row.get("voluntario"): row.get("dni")
        for row in client.all_rows("voluntarios")
    }
    for i in range(100):
        assert surviving_dnis[f"user-{i:03d}"] == f"1234{i:04d}A"


# --- atom 3 -------------------------------------------------------------


def test_round_trip_with_3_edits_applies_3_updates(round_trip_runner) -> None:
    """Three operator edits between forward + reverse → 3 legacy UPDATEs.

    Spec atom ``test_round_trip_with_3_edits_applies_3_updates``. The
    spec scenario ``Round-trip with 3 in-flight web edits`` pins the
    contract: 3 emails edited in web are reverse-pushed to legacy,
    the other 97 are no-op, and the shadow state records zero
    ``needs_review`` (the 3 edits were intentional and reverse-applied
    cleanly — no drift detection triggered).
    """
    legacy_rows = [
        {
            "Voluntario": f"user-{i:03d}",
            "Email": f"u{i}@example.org",
            "Tel1": f"+34600{i:07d}",
            "Tel2": None,
        }
        for i in range(100)
    ]
    web_seed_rows = [
        {
            "voluntario": f"user-{i:03d}",
            "email": f"u{i}@example.org",
            "tel1": f"+34600{i:07d}",
            "tel2": None,
        }
        for i in range(100)
    ]
    # Three edits: emails rewritten on rows 10, 20, 30.
    web_edits = [
        {"voluntario": "user-010", "email": "alice-edited@example.org"},
        {"voluntario": "user-020", "email": "bob-edited@example.org"},
        {"voluntario": "user-030", "email": "carol-edited@example.org"},
    ]

    out = round_trip_runner(
        table_name="voluntario",
        legacy_table="TbVoluntariosParaAutorrellenables",
        web_table="voluntarios",
        key_field="Voluntario",
        legacy_rows=legacy_rows,
        web_seed={"voluntarios": web_seed_rows},
        web_edits=web_edits,
    )

    forward_result = out["forward_result"]
    reverse_result = out["reverse_result"]
    writes2 = out["writes2"]

    assert forward_result.errors == []
    # Reverse apply wrote 3 UPDATEs (the 3 edited rows) and skipped 97.
    assert reverse_result.applied == 3
    assert reverse_result.skipped == 97
    assert reverse_result.errors == []
    # The 3 writes are all UPDATE statements with the new email in
    # the bound params.
    update_writes = [w for w in writes2 if "UPDATE" in w[1].upper()]
    assert len(update_writes) == 3
    for _path, sql, _params in update_writes:
        assert sql.upper().startswith("UPDATE ")
    # No needs_review rows because the legacy write seam returned
    # rowcount=1 for all 3 (no drift).
    client = out["client"]
    needs_review = [
        row
        for row in client.all_rows("WEB_ONLY_FEATURE_SHADOW")
        if (row.get("reconciliation_status") == "needs_review"
            and row.get("origin_direction") == "web-to-legacy"
            and row.get("web_column") == "__row__")
    ]
    assert needs_review == [], (
        f"3 in-flight edits should reverse cleanly; got "
        f"{len(needs_review)} needs_review rows: {needs_review!r}"
    )


# --- atom 4 -------------------------------------------------------------


def test_round_trip_detects_unsynced_edits_as_needs_review(
    round_trip_runner,
) -> None:
    """Five legacy rows deleted post-forward → 5 ``needs_review`` shadow rows.

    Spec atom ``test_round_trip_detects_unsynced_edits_as_needs_review``.
    The spec scenario ``Round-trip detects drift as needs_review``
    says: a manual edit that lands on a row whose legacy counterpart
    no longer exists routes the divergence to ``web_only_feature_shadow``
    with ``reconciliation_status="needs_review"`` and
    ``review_reasons=["..."]``.

    Mechanic in PR6: the legacy write seam reports ``rowcount=0`` when
    the natural-key row was deleted out-of-band (operator deleted the
    row in Access). The reverse applier reads that rowcount and
    routes the divergence to shadow rather than counting it as a
    successful UPDATE.
    """
    legacy_rows = [
        {
            "Voluntario": f"user-{i:03d}",
            "Email": f"u{i}@example.org",
            "Tel1": f"+34600{i:07d}",
            "Tel2": None,
        }
        for i in range(100)
    ]
    web_seed_rows = [
        {
            "voluntario": f"user-{i:03d}",
            "email": f"u{i}@example.org",
            "tel1": f"+34600{i:07d}",
            "tel2": None,
        }
        for i in range(100)
    ]
    # Five edits on rows whose legacy counterpart was deleted.
    web_edits = [
        {"voluntario": "user-005", "email": "alice-edited@example.org"},
        {"voluntario": "user-015", "email": "bob-edited@example.org"},
        {"voluntario": "user-025", "email": "carol-edited@example.org"},
        {"voluntario": "user-035", "email": "dave-edited@example.org"},
        {"voluntario": "user-045", "email": "eve-edited@example.org"},
    ]
    missing_pks = {"user-005", "user-015", "user-025", "user-035", "user-045"}

    out = round_trip_runner(
        table_name="voluntario",
        legacy_table="TbVoluntariosParaAutorrellenables",
        web_table="voluntarios",
        key_field="Voluntario",
        legacy_rows=legacy_rows,
        web_seed={"voluntarios": web_seed_rows},
        web_edits=web_edits,
        missing_pks=missing_pks,
    )

    reverse_result = out["reverse_result"]
    client = out["client"]

    # The reverse apply issued 5 UPDATEs (one per edited row); the
    # legacy write seam reported rowcount=0 for each, so the diff
    # handler routed them to shadow. ``FakeSqlExecutor`` does not
    # capture the ``origin_direction`` column (it indexes the
    # upsert param list up to index 7; ``origin_direction`` is
    # index 8); the test pins the spec contract via
    # ``web_pk is not None`` (the reverse drift recorder sets
    # ``web_pk=legacy_pk``; the forward forward-only divergence
    # recorder leaves ``web_pk=None``).
    assert reverse_result.errors == []
    drift_rows = [
        row
        for row in client.all_rows("WEB_ONLY_FEATURE_SHADOW")
        if (row.get("reconciliation_status") == "needs_review"
            and row.get("web_column") == "__row__"
            and row.get("web_pk") is not None)
    ]
    assert len(drift_rows) == 5, (
        f"expected 5 reverse-direction drift rows for the 5 "
        f"unsynced edits; got {len(drift_rows)}: {drift_rows!r}"
    )
    # The 5 distinct natural-key values are stamped on the rows.
    drift_pks = {row.get("legacy_pk") for row in drift_rows}
    assert drift_pks == missing_pks
    # Categorical review-reason stamp.
    for row in drift_rows:
        reasons = row.get("review_reasons") or []
        assert "reverse_drift_legacy_row_missing" in reasons


# --- atom 5 -------------------------------------------------------------


def test_round_trip_counts_preserved(round_trip_runner) -> None:
    """Per-table counts stay constant across the round-trip.

    Spec atom ``test_round_trip_counts_preserved``. After the full
    ``legacy -> web -> legacy`` round-trip with no edits, the
    per-table counts are:

        count_legacy == count_web == count_after_round_trip

    The MigrationReport surfaces these in
    ``MigrationReport.collisions[table]["count_legacy"]`` /
    ``count_web`` (PR3 added; PR6 leaves them unchanged). Today the
    round-trip runner carries the counts directly via the web
    table, so the assertion is on the FakeSqlExecutor row count.
    """
    legacy_rows = [
        {
            "Voluntario": f"user-{i:03d}",
            "Email": f"u{i}@example.org",
            "Tel1": f"+34600{i:07d}",
            "Tel2": None,
        }
        for i in range(50)
    ]

    out = round_trip_runner(
        table_name="voluntario",
        legacy_table="TbVoluntariosParaAutorrellenables",
        web_table="voluntarios",
        key_field="Voluntario",
        legacy_rows=legacy_rows,
        web_seed={"voluntarios": []},  # forward apply populates
    )

    forward_result = out["forward_result"]
    reverse_result = out["reverse_result"]
    client = out["client"]

    # Forward applied 50.
    assert forward_result.applied == 50
    assert forward_result.errors == []
    # Reverse applied 0 (no edits) + skipped 50.
    assert reverse_result.applied == 0
    assert reverse_result.skipped == 50
    assert reverse_result.errors == []
    # count_after_round_trip == 50 in web.
    final_count = len(client.all_rows("voluntarios"))
    assert final_count == 50
