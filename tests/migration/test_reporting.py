"""Tests for ``migration.reporting`` MigrationReport extensions (PR3/M1).

Per design D11 (corrections B): ADD to existing ``MigrationReport``:

- ``counts: dict[str, int]`` (per-table ``{count_legacy, count_web}``)
- ``source_hashes: dict[str, str]`` (per-table SHA-256)
- ``collisions: dict[str, int]`` (per-table counters, e.g.
  ``{"preserve_advances": 0, "row_divergences": N}``)

All three are added via ``field(default_factory=dict)`` so pre-PR3
reports (and the existing ``_sample_report`` fixture in
``tests/test_migration.py``) stay valid.

``ApplyResult`` is UNCHANGED per design D11.

Hard Rules honoured:

- Rule 1 (fixture gate): every test constructs its own report with
  deterministic values.
- Rule 4 (no humo): assertions pin concrete JSON substrings and
  dataclass equality, not absence of error.
- Rule 6 (refactor-safety): tests assert JSON shape, not internal
  helper call order.

Three paths per slice (web-tdd-philosophy Rule 5):

- happy: defaults, explicit kwargs, roundtrip serialization
- sad: a non-serializable value raises ``TypeError`` loudly
- edge: empty dicts serialize as ``{}``; PII/path tokens never appear
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from migration.reporting import Conflict, Diff, MigrationReport


def _sample_report(**overrides: object) -> MigrationReport:
    """Build a deterministic MigrationReport for assertions."""
    fields: dict[str, object] = {
        "direction": "legacy-to-web",
        "mode": "dry-run",
        "dry_run": True,
        "applied": False,
        "started_at": datetime(2026, 7, 11, 12, 0, 0, tzinfo=UTC),
        "finished_at": datetime(2026, 7, 11, 12, 0, 5, 250000, tzinfo=UTC),
        "duration_seconds": 5.25,
        "diffs": (),
        "conflicts": (),
        "backup_path": None,
        "error": None,
    }
    fields.update(overrides)
    return MigrationReport(**fields)  # type: ignore[arg-type]


def _sample_diff(op: str = "INSERT", key: str = "animal-001") -> Diff:
    """Build a deterministic Diff for the markdown-helper tests."""
    return Diff(op=op, key=key)  # type: ignore[arg-type]


def _sample_conflict(table: str = "animales") -> Conflict:
    """Build a deterministic Conflict for the markdown-helper tests."""
    return Conflict(
        table=table,
        key="animal-001",
        reason="modified_both_sides",
    )


# --------------------------------------------------------------------------
# Backward-compatible default factories
# --------------------------------------------------------------------------


class TestDefaultFactories:
    """Pre-PR3 callers can build ``MigrationReport`` without the new fields."""

    def test_report_without_new_fields_has_empty_dicts(self) -> None:
        """Constructing without counts/source_hashes/collisions yields empty dicts.

        This is the backward-compatibility guarantee for every existing
        caller (production code and tests) that built a ``MigrationReport``
        before PR3.
        """
        report = _sample_report()
        assert report.counts == {}
        assert report.source_hashes == {}
        assert report.collisions == {}

    def test_report_with_new_fields_keeps_values(self) -> None:
        report = _sample_report(
            counts={"animal": {"count_legacy": 100, "count_web": 90}},
            source_hashes={"animal": "a" * 64},
            collisions={"animal": {"preserve_advances": 0, "row_divergences": 2}},
        )
        assert report.counts == {
            "animal": {"count_legacy": 100, "count_web": 90}
        }
        assert report.source_hashes == {"animal": "a" * 64}
        assert report.collisions == {
            "animal": {"preserve_advances": 0, "row_divergences": 2}
        }

    def test_report_is_immutable(self) -> None:
        """``MigrationReport`` is a frozen dataclass (slots + frozen)."""
        report = _sample_report()
        with pytest.raises((AttributeError, Exception)):
            report.counts = {"animal": {"count_legacy": 1, "count_web": 0}}  # type: ignore[misc]


# --------------------------------------------------------------------------
# JSON serialization
# --------------------------------------------------------------------------


class TestJsonSerialization:
    """``to_json()`` round-trips the new fields and exposes no PII."""

    def test_json_includes_counts_source_hashes_collisions(self) -> None:
        report = _sample_report(
            counts={"animal": {"count_legacy": 100, "count_web": 90}},
            source_hashes={"animal": "a" * 64, "voluntario": "b" * 64},
            collisions={"animal": {"preserve_advances": 0, "row_divergences": 2}},
        )
        raw = report.to_json()
        loaded = json.loads(raw)
        assert loaded["counts"] == {
            "animal": {"count_legacy": 100, "count_web": 90}
        }
        assert loaded["source_hashes"] == {
            "animal": "a" * 64,
            "voluntario": "b" * 64,
        }
        assert loaded["collisions"] == {
            "animal": {"preserve_advances": 0, "row_divergences": 2}
        }

    def test_json_with_default_factories_serializes_empty_dicts(self) -> None:
        report = _sample_report()
        raw = report.to_json()
        loaded = json.loads(raw)
        assert loaded["counts"] == {}
        assert loaded["source_hashes"] == {}
        assert loaded["collisions"] == {}

    def test_json_omits_raw_paths_and_pii_tokens(self) -> None:
        """The serialized report must not embed paths or PII markers.

        The fields we added are counts (int) and hashes (hex). Neither
        field accepts raw paths. ``backup_path`` already exists and is
        operator-set (PR3 does NOT remove it because some web-to-legacy
        reports legitimately carry the pre-flight backup path).
        """
        report = _sample_report(
            counts={"animal": {"count_legacy": 1, "count_web": 0}},
            source_hashes={"animal": "a" * 64},
            collisions={"animal": {"preserve_advances": 0, "row_divergences": 0}},
        )
        raw = report.to_json()
        for forbidden in ("DNI", "Email", "Tel1", "Tel2"):
            # The PII tokens are NOT in the JSON values; they are
            # safe to grep for.
            assert forbidden not in raw, (
                f"forbidden token {forbidden!r} leaked into report JSON"
            )

    def test_json_with_collisions_omits_raw_pk_values(self) -> None:
        """Collision counters must NOT embed the colliding PKs.

        Per design D11: ``collisions`` carries COUNTS only. The
        operator-facing detail (which PKs collided) lives in the
        ``web_only_feature_shadow`` table and the
        ``MigrationReport.conflicts`` list, NOT in the new
        ``collisions`` dict.
        """
        report = _sample_report(
            collisions={"voluntario": {"preserve_advances": 5, "row_divergences": 0}},
        )
        raw = report.to_json()
        # Even though we did not put a DNI value here, the JSON must
        # not accidentally serialize one (the schema is ``int``).
        loaded = json.loads(raw)
        collisions = loaded["collisions"]
        # Walk the entire structure and assert no string values look like PII.
        def _walk(value: object) -> None:
            if isinstance(value, dict):
                for v in value.values():
                    _walk(v)
            elif isinstance(value, list):
                for v in value:
                    _walk(v)
            elif isinstance(value, str):
                for forbidden in ("DNI", "Email", "Tel1", "Tel2"):
                    assert forbidden not in value

        _walk(collisions)


# --------------------------------------------------------------------------
# ApplyResult unchanged
# --------------------------------------------------------------------------


class TestApplyResultUnchanged:
    """``ApplyResult`` is UNCHANGED per design D11.

    PR3 only extends ``MigrationReport``. The lighter per-table
    dataclass ``ApplyResult`` keeps its ``{table_name, applied,
    skipped, errors}`` shape so the CLI surface (and its tests) stay
    untouched.
    """

    def test_apply_result_has_no_counts_field(self) -> None:
        from dataclasses import fields

        from migration.apply import ApplyResult

        names = {f.name for f in fields(ApplyResult)}
        assert "counts" not in names
        assert "source_hashes" not in names
        assert "collisions" not in names
        # Sanity: the four-field shape is still the contract.
        assert names == {"table_name", "applied", "skipped", "errors"}

    def test_apply_result_construction_still_works(self) -> None:
        from migration.apply import ApplyResult

        result = ApplyResult(table_name="animal", applied=5, skipped=1)
        assert result.table_name == "animal"
        assert result.applied == 5
        assert result.skipped == 1
        assert result.errors == []


# --------------------------------------------------------------------------
# Markdown rendering — section helpers and end-to-end shape
# --------------------------------------------------------------------------
#
# Each helper used to be inlined in ``_md_source_identity`` /
# ``_md_metrics`` and drove their CRAP score above the grade-A cap.
# Splitting them lowered CC and lets us cover every branch with a unit
# test; the integration below pins the byte-for-byte output that
# downstream tests in ``tests/test_migration.py`` rely on.


class TestMdMetrics:
    """``_md_metric_counts`` + ``_md_metrics_table`` + ``_md_metrics``."""

    def test_md_metric_counts_with_empty_diffs(self) -> None:
        """Empty diffs + zero conflicts → every counter is 0."""
        report = _sample_report()
        assert report._md_metric_counts() == {
            "INSERT": 0,
            "UPDATE": 0,
            "DELETE": 0,
            "NOOP": 0,
            "Conflict": 0,
            "Total": 0,
        }

    def test_md_metric_counts_with_single_insert(self) -> None:
        """A single INSERT bumps INSERT and Total; other ops stay at 0."""
        report = _sample_report(diffs=(_sample_diff("INSERT", "a"),))
        counts = report._md_metric_counts()
        assert counts == {
            "INSERT": 1,
            "UPDATE": 0,
            "DELETE": 0,
            "NOOP": 0,
            "Conflict": 0,
            "Total": 1,
        }

    def test_md_metric_counts_with_mixed_ops(self) -> None:
        """Mixed INSERT/UPDATE/DELETE/NOOP → per-op counts and total match."""
        from migration.reporting import Diff

        diffs = (
            Diff(op="INSERT", key="i1"),
            Diff(op="INSERT", key="i2"),
            Diff(op="UPDATE", key="u1"),
            Diff(op="DELETE", key="d1"),
            Diff(op="DELETE", key="d2"),
            Diff(op="DELETE", key="d3"),
            Diff(op="NOOP", key="n1"),
        )
        report = _sample_report(
            diffs=diffs,
            conflicts=(_sample_conflict(),),
        )
        assert report._md_metric_counts() == {
            "INSERT": 2,
            "UPDATE": 1,
            "DELETE": 3,
            "NOOP": 1,
            "Conflict": 1,
            "Total": 7,
        }

    def test_md_metrics_renders_table_with_mixed_diffs(self) -> None:
        """``_md_metrics`` renders the table with exact per-op rows."""
        from migration.reporting import Diff

        diffs = (
            Diff(op="INSERT", key="i1"),
            Diff(op="UPDATE", key="u1"),
            Diff(op="DELETE", key="d1"),
            Diff(op="NOOP", key="n1"),
        )
        report = _sample_report(diffs=diffs)
        md = report._md_metrics()
        assert "| INSERT | 1 |" in md
        assert "| UPDATE | 1 |" in md
        assert "| DELETE | 1 |" in md
        assert "| NOOP | 1 |" in md
        assert "| Conflict | 0 |" in md
        assert "| Total | 4 |" in md

    def test_md_metrics_table_with_zero_total(self) -> None:
        """Empty diffs render the zero-counts table — guards the 0-row branch."""
        report = _sample_report()
        md = report._md_metrics()
        assert "| INSERT | 0 |" in md
        assert "| NOOP | 0 |" in md
        assert "| Total | 0 |" in md


class TestMdSourceIdentitySubtables:
    """The three sub-helpers introduced by the CRAP ratchet split."""

    def test_md_counts_table_is_empty_when_counts_is_empty(self) -> None:
        report = _sample_report()
        assert report._md_counts_table() == ""

    def test_md_counts_table_renders_one_row_per_table(self) -> None:
        """Each counts entry becomes a row with the legacy/web columns."""
        report = _sample_report(
            counts={
                "animales": {"count_legacy": 100, "count_web": 90},
                "voluntarios": {"count_legacy": 50, "count_web": 50},
            },
        )
        md = report._md_counts_table()
        assert md.startswith("### Counts\n\n")
        assert "| Table | count_legacy | count_web |" in md
        assert "|---|---|---|" in md
        assert "| animales | 100 | 90 |" in md
        assert "| voluntarios | 50 | 50 |" in md
        # Trailing blank line, byte-for-byte parity with the pre-split output.
        assert md.endswith("\n")

    def test_md_counts_table_defaults_missing_legacy_or_web_to_empty(self) -> None:
        """When a counts entry omits one of the keys, the cell is empty."""
        report = _sample_report(
            counts={"animales": {"count_legacy": 1}},
        )
        md = report._md_counts_table()
        # ``count_web`` is missing → cell is empty (matches pre-split behavior).
        assert "| animales | 1 |  |" in md

    def test_md_source_hashes_table_is_empty_when_source_hashes_is_empty(
        self,
    ) -> None:
        report = _sample_report()
        assert report._md_source_hashes_table() == ""

    def test_md_source_hashes_table_renders_one_row_per_table(self) -> None:
        """Each hash entry becomes a backtick-wrapped row."""
        report = _sample_report(
            source_hashes={
                "animales": "a" * 64,
                "voluntarios": "b" * 64,
            },
        )
        md = report._md_source_hashes_table()
        assert md.startswith("### Source hashes\n\n")
        assert "| Table | sha256 |" in md
        assert "|---|---|" in md
        assert f"| animales | `{'a' * 64}` |" in md
        assert f"| voluntarios | `{'b' * 64}` |" in md
        assert md.endswith("\n")

    def test_md_collisions_table_is_empty_when_collisions_is_empty(self) -> None:
        report = _sample_report()
        assert report._md_collisions_table() == ""

    def test_md_collisions_table_flattens_nested_counters(self) -> None:
        """The nested ``{table: {key: value}}`` shape flattens to one row per key."""
        report = _sample_report(
            collisions={
                "animales": {
                    "preserve_advances": 0,
                    "row_divergences": 2,
                },
                "voluntarios": {"preserve_advances": 5, "row_divergences": 0},
            },
        )
        md = report._md_collisions_table()
        assert md.startswith("### Collisions\n\n")
        assert "| Table | key | count |" in md
        assert "|---|---|---|" in md
        assert "| animales | preserve_advances | 0 |" in md
        assert "| animales | row_divergences | 2 |" in md
        assert "| voluntarios | preserve_advances | 5 |" in md
        assert "| voluntarios | row_divergences | 0 |" in md
        assert md.endswith("\n")


class TestMdSourceIdentityIntegration:
    """End-to-end byte-for-byte shape of ``_md_source_identity`` + ``to_markdown``.

    The split replaced one big ``_md_source_identity`` body with three
    sub-helpers. The byte-for-byte output must stay identical so any
    downstream test that pins a substring (e.g. ``## Source Identity``)
    keeps passing.
    """

    def test_md_source_identity_returns_empty_when_all_subfields_empty(self) -> None:
        report = _sample_report()
        assert report._md_source_identity() == ""
        # The full markdown must not contain a stray ``## Source Identity`` header.
        assert "## Source Identity" not in report.to_markdown()

    def test_md_source_identity_with_only_counts(self) -> None:
        report = _sample_report(
            counts={"animales": {"count_legacy": 100, "count_web": 90}},
        )
        md = report._md_source_identity()
        assert md.startswith("## Source Identity\n\n")
        assert "### Counts" in md
        assert "### Source hashes" not in md
        assert "### Collisions" not in md
        # The other sub-helpers are absent, so their headers don't appear.
        assert "| animales | 100 | 90 |" in md

    def test_md_source_identity_with_only_source_hashes(self) -> None:
        report = _sample_report(source_hashes={"animales": "a" * 64})
        md = report._md_source_identity()
        assert "### Source hashes" in md
        assert "### Counts" not in md
        assert "### Collisions" not in md

    def test_md_source_identity_with_only_collisions(self) -> None:
        report = _sample_report(
            collisions={"animales": {"preserve_advances": 3, "row_divergences": 0}},
        )
        md = report._md_source_identity()
        assert "### Collisions" in md
        assert "### Counts" not in md
        assert "### Source hashes" not in md

    def test_md_source_identity_with_all_three_subfields(self) -> None:
        """All three populated → all three sub-tables render in order."""
        report = _sample_report(
            counts={"animales": {"count_legacy": 100, "count_web": 90}},
            source_hashes={"animales": "a" * 64},
            collisions={"animales": {"preserve_advances": 0, "row_divergences": 2}},
        )
        md = report._md_source_identity()
        # Section order is counts → source_hashes → collisions.
        counts_pos = md.index("### Counts")
        hashes_pos = md.index("### Source hashes")
        collisions_pos = md.index("### Collisions")
        assert counts_pos < hashes_pos < collisions_pos

    def test_to_markdown_preserves_byte_shape_for_source_identity(self) -> None:
        """The end-to-end markdown keeps the pre-split byte-for-byte output."""
        report = _sample_report(
            counts={"animales": {"count_legacy": 100, "count_web": 90}},
            source_hashes={"animales": "a" * 64, "voluntarios": "b" * 64},
            collisions={
                "animales": {"preserve_advances": 0, "row_divergences": 2},
                "voluntarios": {"preserve_advances": 5, "row_divergences": 0},
            },
        )
        md = report.to_markdown()
        # Every row the pre-split ``_md_source_identity`` would have rendered.
        assert "## Source Identity" in md
        assert "### Counts" in md
        assert "| animales | 100 | 90 |" in md
        assert "### Source hashes" in md
        assert f"| animales | `{'a' * 64}` |" in md
        assert f"| voluntarios | `{'b' * 64}` |" in md
        assert "### Collisions" in md
        assert "| animales | preserve_advances | 0 |" in md
        assert "| voluntarios | row_divergences | 0 |" in md
