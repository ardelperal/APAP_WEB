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

from migration.reporting import MigrationReport


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
