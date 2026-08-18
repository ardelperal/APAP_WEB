"""Strict TDD atoms for the VOL-03 fuzzy dedup pipeline (issue #36).

The pipeline deduplicates free-text references to voluntarios that live
across the legacy Access tables (``TbVoluntariosParaAutorrellenables``,
``TbEntradas``, ``TbAdopcion``, ``TbAcogidaAnimal``, ``TbTerapias``).

Acceptance criteria pinned by these atoms (cross-ref
``docs/architecture/decisiones-proyecto.md`` + ``docs/legacy-volunteer-roles.md`` +
issue #36):

1. Fuzzy match collapses similar free-text names across 3+ legacy tables.
2. ``DNI`` is a secondary key: identical DNI across rows forces a merge
   even when the name strings differ (typo, married name, etc.).
3. Same name + different DNI does NOT auto-merge — the cluster is
   flagged for manual review.
4. The pipeline is idempotent: re-running with the same input produces
   byte-identical output (AC #4 / #5 of issue #36).
5. ``DNI`` values never appear in clear text in any emitted log record
   (the closed ``REDACTED_FIELDS`` invariant + ``log_safe`` contract).

The pure algorithm lives in ``migration.volunteer_dedup`` and has NO
transport / DB / dysflow dependency: it accepts a list of
``VolunteerRef`` dicts and returns a list of ``MergedCluster`` dataclass
instances. The CLI bridge (``migration.cli_volunteer_dedup``) is a thin
shell over the pure function (issue spec accepts JSON file output as a
valid review interface for this PR).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Any

import pytest

from migration.volunteer_dedup import (
    MergedCluster,
    VolunteerRef,
    dedup_volunteers,
)


def _ref(
    name: str,
    *,
    source_table: str = "TbEntradas",
    source_row_id: str = "row-1",
    dni: str | None = None,
) -> VolunteerRef:
    """Test helper: build a ``VolunteerRef`` with sensible defaults.

    The defaults make every ref come from a different legacy row of
    ``TbEntradas`` so each ref is a singleton unless the algorithm
    groups it with a sibling.
    """
    return VolunteerRef(
        name=name,
        source_table=source_table,
        source_row_id=source_row_id,
        dni=dni,
    )


# --- Acceptance criterion 1: fuzzy match across 3+ legacy tables --------


def test_dedup_collapses_identical_names_from_three_legacy_tables() -> None:
    """Three refs with the SAME name across 3 legacy tables -> 1 cluster.

    The free-text "Maria Garcia" lives in ``TbEntradas``,
    ``TbAdopcion`` and ``TbAcogidaAnimal`` (the legacy has no FK —
    each table stores the name independently). The pipeline MUST
    recognise them as the same person.
    """
    refs = [
        _ref("Maria Garcia", source_table="TbEntradas", source_row_id="e-1"),
        _ref("Maria Garcia", source_table="TbAdopcion", source_row_id="a-1"),
        _ref("Maria Garcia", source_table="TbAcogidaAnimal", source_row_id="g-1"),
    ]
    clusters = dedup_volunteers(refs)
    assert len(clusters) == 1, (
        f"identical names across 3 legacy tables must collapse to 1 cluster; "
        f"got {len(clusters)}: {[c.canonical_name for c in clusters]}"
    )
    cluster = clusters[0]
    assert cluster.canonical_name == "Maria Garcia"
    assert {s.source_table for s in cluster.sources} == {
        "TbEntradas",
        "TbAdopcion",
        "TbAcogidaAnimal",
    }
    assert cluster.decision == "auto_merged"
    assert cluster.reason == "exact_name_match"


def test_dedup_collapses_similar_names_via_fuzzy_match() -> None:
    """Fuzzy match: a typo'd variant in one table collapses into the
    canonical cluster.

    "María García" (TbEntradas) and "Maria Garcia" (TbAdopcion) are
    the same person — the diacritic difference is typical of legacy
    free-text. Without the fuzzy stage these would be two clusters.
    """
    refs = [
        _ref("María García", source_table="TbEntradas", source_row_id="e-1"),
        _ref("Maria Garcia", source_table="TbAdopcion", source_row_id="a-1"),
    ]
    clusters = dedup_volunteers(refs)
    assert len(clusters) == 1, (
        f"accent-stripped names must collapse via fuzzy match; got "
        f"{len(clusters)} clusters: {[c.canonical_name for c in clusters]}"
    )
    assert clusters[0].decision == "auto_merged"
    assert clusters[0].reason in {"fuzzy_name_match", "exact_name_match"}


def test_dedup_handles_three_plus_distinct_legacy_tables() -> None:
    """Pipeline accepts refs from N>=3 legacy tables without dropping any.

    Tests the matrix shape: 5 refs across 5 different legacy tables
    with the same name -> 1 cluster carrying all 5 source refs.
    """
    refs = [
        _ref("Maria Garcia", source_table=t, source_row_id=f"{t}-1")
        for t in (
            "TbVoluntariosParaAutorrellenables",
            "TbEntradas",
            "TbAdopcion",
            "TbAcogidaAnimal",
            "TbTerapias",
        )
    ]
    clusters = dedup_volunteers(refs)
    assert len(clusters) == 1
    assert len(clusters[0].sources) == 5
    assert {s.source_table for s in clusters[0].sources} == {
        "TbVoluntariosParaAutorrellenables",
        "TbEntradas",
        "TbAdopcion",
        "TbAcogidaAnimal",
        "TbTerapias",
    }


# --- Acceptance criterion 2: DNI as secondary key ------------------------


def test_dedup_dni_exact_match_collapses_different_names() -> None:
    """Identical DNI across rows forces a merge even when names differ.

    Scenario: a married-name change. ``"Maria Garcia Lopez"`` (legacy
    table X) and ``"Maria Lopez Garcia"`` (legacy table Y) are the
    same person because they share the same DNI. Without the DNI
    override the fuzzy stage might not reach the threshold (the
    lastname reorder drops the score below 85) and the rows would
    stay split. With DNI as a secondary key they collapse.
    """
    refs = [
        _ref(
            "Maria Garcia Lopez",
            source_table="TbEntradas",
            source_row_id="e-1",
            dni="12345678A",
        ),
        _ref(
            "Maria Lopez Garcia",
            source_table="TbAdopcion",
            source_row_id="a-1",
            dni="12345678A",
        ),
    ]
    clusters = dedup_volunteers(refs)
    assert len(clusters) == 1, (
        f"identical DNI must force a merge; got {len(clusters)} clusters"
    )
    assert clusters[0].decision == "auto_merged"
    assert clusters[0].reason == "dni_exact_match"
    assert clusters[0].dni == "12345678A"


# --- Acceptance criterion 3: ambiguous matches flagged for review -------


def test_dedup_dni_mismatch_flags_for_manual_review_not_auto_merged() -> None:
    """Same name + DIFFERENT DNI does NOT auto-merge.

    Two different people can legitimately share a common name in the
    legacy ("Maria Garcia" the voluntaria de entrada vs. "Maria
    Garcia" the sanitaria). The algorithm MUST NOT silently merge
    them — it has to surface the ambiguity for an operator to
    resolve.
    """
    refs = [
        _ref(
            "Maria Garcia",
            source_table="TbEntradas",
            source_row_id="e-1",
            dni="12345678A",
        ),
        _ref(
            "Maria Garcia",
            source_table="TbAdopcion",
            source_row_id="a-1",
            dni="87654321B",
        ),
    ]
    clusters = dedup_volunteers(refs)
    # Two clusters: the algorithm recognises them as separate people.
    assert len(clusters) == 2, (
        f"different DNI must keep refs separate; got {len(clusters)}"
    )
    # Both clusters are flagged for manual review because the
    # algorithm had to make a decision on a name-match that the DNI
    # contradicted.
    assert all(c.decision == "needs_review" for c in clusters), (
        f"clusters must carry needs_review when the algorithm "
        f"considered a merge but the DNI disagreed; got "
        f"{[c.decision for c in clusters]}"
    )
    assert all(c.reason == "ambiguous_dni_collision" for c in clusters)


def test_dedup_dni_consensus_merges_partial_dni_set() -> None:
    """When only some refs carry a DNI, consensus merges the rest.

    "Maria Garcia" in TbEntradas (DNI=12345678A), "Maria Garcia" in
    TbAdopcion (no DNI), and "Maria Garcia" in TbAcogidaAnimal
    (DNI=12345678A). The two refs that share the DNI force a
    cluster; the no-DNI ref joins because the fuzzy match puts it
    inside the cluster and there is no conflicting DNI to keep it
    apart.
    """
    refs = [
        _ref(
            "Maria Garcia",
            source_table="TbEntradas",
            source_row_id="e-1",
            dni="12345678A",
        ),
        _ref("Maria Garcia", source_table="TbAdopcion", source_row_id="a-1"),
        _ref(
            "Maria Garcia",
            source_table="TbAcogidaAnimal",
            source_row_id="g-1",
            dni="12345678A",
        ),
    ]
    clusters = dedup_volunteers(refs)
    assert len(clusters) == 1
    assert clusters[0].dni == "12345678A"
    assert len(clusters[0].sources) == 3
    assert clusters[0].decision == "auto_merged"


# --- Singleton handling -------------------------------------------------


def test_dedup_unique_rows_become_singletons() -> None:
    """Distinct names -> singleton clusters with decision='unique'."""
    refs = [
        _ref("Maria Garcia", source_table="TbEntradas", source_row_id="e-1"),
        _ref("Jon Smith", source_table="TbAdopcion", source_row_id="a-1"),
        _ref("Ana Lopez", source_table="TbAcogidaAnimal", source_row_id="g-1"),
    ]
    clusters = dedup_volunteers(refs)
    assert len(clusters) == 3
    assert all(c.decision == "unique" for c in clusters)
    assert all(len(c.sources) == 1 for c in clusters)
    # Order is preserved by input order (idempotence check below).
    canonical_names = [c.canonical_name for c in clusters]
    assert canonical_names == ["Maria Garcia", "Jon Smith", "Ana Lopez"]


def test_dedup_empty_input_returns_empty_list() -> None:
    """Empty input -> empty output, no exception."""
    assert dedup_volunteers([]) == []


# --- Acceptance criterion 4 + 5: idempotence ----------------------------


def test_dedup_is_idempotent_double_run() -> None:
    """Running the pipeline twice on the same input yields identical output.

    Issue #36 AC #4 (deduplicacion idempotente) and #5 (idempotencia
    probada con doble ejecucion). The two lists of clusters MUST be
    byte-equal when serialised to JSON — no hidden order drift, no
    timestamp leakage, no random tie-breaking.
    """
    refs = [
        _ref("Maria Garcia", source_table="TbEntradas", source_row_id="e-1"),
        _ref("Maria Garcia", source_table="TbAdopcion", source_row_id="a-1"),
        _ref("María García", source_table="TbAcogidaAnimal", source_row_id="g-1"),
        _ref(
            "Maria Garcia Lopez",
            source_table="TbEntradas",
            source_row_id="e-2",
            dni="12345678A",
        ),
        _ref(
            "Maria Lopez Garcia",
            source_table="TbAdopcion",
            source_row_id="a-2",
            dni="12345678A",
        ),
        _ref("Jon Smith", source_table="TbEntradas", source_row_id="e-3"),
    ]
    first = dedup_volunteers(refs)
    second = dedup_volunteers(refs)
    assert _clusters_to_json(first) == _clusters_to_json(second)


def test_dedup_is_pure_no_input_mutation() -> None:
    """The function does not mutate its input list of refs.

    Idempotence requires that the function be referentially
    transparent on its inputs. A pure function that mutates would
    pass a single-run assertion but fail on a second run.
    """
    refs = [
        _ref("Maria Garcia", source_table="TbEntradas", source_row_id="e-1"),
        _ref("Jon Smith", source_table="TbAdopcion", source_row_id="a-1"),
    ]
    snapshot_before = [asdict(r) for r in refs]
    dedup_volunteers(refs)
    snapshot_after = [asdict(r) for r in refs]
    assert snapshot_before == snapshot_after


# --- PII redaction invariant --------------------------------------------


def test_dedup_does_not_emit_raw_dni_in_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When the dedup logs summary metrics it MUST NOT leak raw DNI.

    Pins the AGENTS.md §32.P2 (no insecure defaults that still boot)
    and §18 (privacy default-deny) contract: even an internal debug
    log that mentions a DNI value fails the test. The implementation
    is expected to use ``log_safe`` from ``app.core.logging`` so any
    field name in ``REDACTED_FIELDS`` (``dni``, ``tel1``, ``tel2``)
    is automatically scrubbed.

    The atom feeds a known DNI value (``"12345678A"``) and asserts
    that ``caplog.text`` does NOT contain it.
    """
    raw_dni = "12345678A"
    refs = [
        _ref(
            "Maria Garcia",
            source_table="TbEntradas",
            source_row_id="e-1",
            dni=raw_dni,
        ),
        _ref(
            "Maria Garcia",
            source_table="TbAdopcion",
            source_row_id="a-1",
            dni=raw_dni,
        ),
    ]
    with caplog.at_level(logging.INFO, logger="app"):
        dedup_volunteers(refs)
    assert raw_dni not in caplog.text, (
        "dedup emitted a raw DNI value into the log stream — "
        "use log_safe(..., dni=...) so the redaction filter scrubs it. "
        f"caplog.text={caplog.text!r}"
    )


# --- helpers ------------------------------------------------------------


def _clusters_to_json(clusters: list[MergedCluster]) -> str:
    """Stable JSON serialisation for idempotence comparison.

    The dataclass.asdict + json.dumps with sorted keys gives us a
    canonical byte representation that does not depend on dict
    ordering or non-deterministic source iteration order.
    """

    def _stable(obj: Any) -> Any:
        if isinstance(obj, VolunteerRef):
            return asdict(obj)
        if isinstance(obj, MergedCluster):
            return {
                "canonical_name": obj.canonical_name,
                "dni": obj.dni,
                "decision": obj.decision,
                "reason": obj.reason,
                "confidence": obj.confidence,
                "sources": sorted(
                    (_stable(s) for s in obj.sources),
                    key=lambda d: (d["source_table"], d["source_row_id"]),
                ),
            }
        raise TypeError(f"cannot serialise {type(obj).__name__}")

    return json.dumps([_stable(c) for c in clusters], sort_keys=True, ensure_ascii=False)

