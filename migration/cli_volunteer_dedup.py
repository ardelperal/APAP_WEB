"""JSON-file bridge for ``migration.volunteer_dedup``.

The operator reads a list of free-text volunteer references from
one or more legacy tables, runs the dedup, and writes the resulting
clusters to a JSON file that they can open in any editor to
review the ambiguous cases (``decision == "needs_review"``).

This module is a deliberately thin shell over the pure
:func:`migration.volunteer_dedup.dedup_volunteers` function: it
adds I/O (JSON read/write) and a ``--summary`` flag for the
non-interactive default mode. The full interactive y/n review
loop is deliberately deferred to a follow-up PR (per issue #36
spec which accepts a JSON output as a valid review interface for
this slice).

The bridge is invoked via :func:`run_volunteer_dedup` (testable
in isolation) and not wired into ``migration.cli`` directly —
``migration.cli`` is already at the 700-line module-size budget
(AGENTS.md rule 21) and the dedup subcommand is a separate
concept that lives next to its helper.

Usage::

    # Read refs from a JSON file, write clusters to another JSON file.
    python -m migration.cli_volunteer_dedup --input refs.json --output clusters.json

    # Print a one-line summary to stdout instead of writing a file.
    python -m migration.cli_volunteer_dedup --input refs.json --summary

The input JSON shape is::

    {
      "refs": [
        {"name": "...", "source_table": "...", "source_row_id": "...", "dni": "..."},
        ...
      ],
      "fuzzy_threshold": 85  # optional, default 85
    }

The output JSON shape is::

    {
      "clusters": [
        {
          "canonical_name": "...",
          "dni": "..." | null,
          "decision": "auto_merged" | "needs_review" | "unique",
          "reason": "...",
          "confidence": 100.0 | null,
          "sources": [
            {"name": "...", "source_table": "...", "source_row_id": "...", "dni": "..."},
            ...
          ]
        },
        ...
      ]
    }
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from typing import IO, Any

from migration.volunteer_dedup import (
    DEFAULT_FUZZY_THRESHOLD,
    MergedCluster,
    VolunteerRef,
    dedup_volunteers,
)


def _parse_input(payload: dict[str, Any]) -> tuple[list[VolunteerRef], int]:
    """Parse the input JSON payload into a list of :class:`VolunteerRef`.

    Validates the shape: ``refs`` must be a list of dicts with at
    least ``name`` / ``source_table`` / ``source_row_id``. ``dni``
    is optional and defaults to ``None``. The fuzzy threshold is
    read from the payload if present; otherwise the default is
    used.

    Raises:
        ValueError: when the payload is missing keys, has the
            wrong types, or carries a non-int threshold.
    """
    if "refs" not in payload:
        raise ValueError("input JSON must contain a 'refs' array")
    refs_raw = payload["refs"]
    if not isinstance(refs_raw, list):
        raise ValueError(f"input JSON 'refs' must be a list; got {type(refs_raw).__name__}")
    refs: list[VolunteerRef] = []
    for index, entry in enumerate(refs_raw):
        if not isinstance(entry, dict):
            raise ValueError(
                f"refs[{index}] must be a dict; got {type(entry).__name__}"
            )
        missing = [k for k in ("name", "source_table", "source_row_id") if k not in entry]
        if missing:
            raise ValueError(
                f"refs[{index}] missing required keys: {sorted(missing)}"
            )
        refs.append(
            VolunteerRef(
                name=str(entry["name"]),
                source_table=str(entry["source_table"]),
                source_row_id=str(entry["source_row_id"]),
                dni=(
                    str(entry["dni"])
                    if entry.get("dni") is not None
                    and str(entry["dni"]).strip()
                    else None
                ),
            )
        )
    threshold = payload.get("fuzzy_threshold", DEFAULT_FUZZY_THRESHOLD)
    if not isinstance(threshold, int) or not 0 <= threshold <= 100:
        raise ValueError(
            f"fuzzy_threshold must be an int in [0, 100]; got {threshold!r}"
        )
    return refs, threshold


def _cluster_to_dict(cluster: MergedCluster) -> dict[str, Any]:
    """Serialise a :class:`MergedCluster` to a JSON-safe dict.

    ``asdict`` walks the dataclass + nested dataclass sources
    and produces a plain-dict view; ``json.dumps`` handles the
    actual encoding. No raw PII sanitisation is needed at this
    layer because the JSON output IS the operator review surface —
    they have legitimate access to the names / DNIs. The PII
    redaction invariant (no raw DNI in any log) is enforced at
    :func:`app.core.logging.log_safe` and pinned by
    ``tests/migration/test_volunteer_dedup.py::test_dedup_does_not_emit_raw_dni_in_logs``.
    """
    return {
        "canonical_name": cluster.canonical_name,
        "dni": cluster.dni,
        "decision": cluster.decision,
        "reason": cluster.reason,
        "confidence": cluster.confidence,
        "sources": [asdict(src) for src in cluster.sources],
    }


def _format_summary(clusters: Sequence[MergedCluster]) -> str:
    """Render a single-line summary for the ``--summary`` mode.

    Format: ``total=N auto_merged=M needs_review=K unique=U`` so
    log scrapers can parse it without regex on free-form text.
    Mirrors the ``apap-migrate`` operator-facing line format
    (``status=...`` / ``reason=...``).
    """
    auto_merged = sum(1 for c in clusters if c.decision == "auto_merged")
    needs_review = sum(1 for c in clusters if c.decision == "needs_review")
    unique = sum(1 for c in clusters if c.decision == "unique")
    return (
        f"volunteer-dedup: status=ok "
        f"total={len(clusters)} "
        f"auto_merged={auto_merged} "
        f"needs_review={needs_review} "
        f"unique={unique}\n"
    )


def run_volunteer_dedup(
    args: argparse.Namespace,
    *,
    input_stream: IO[str] | None = None,
    output_stream: IO[str] | None = None,
) -> int:
    """Body of ``python -m migration.cli_volunteer_dedup``.

    Args:
        args: the parsed argparse namespace (carries ``--input``,
            ``--output``, ``--summary``).
        input_stream: optional override for the input source. When
            provided, the function reads from this stream instead
            of opening ``args.input`` as a file or reading stdin.
            Tests inject ``io.StringIO`` to keep the suite
            hermetic; production passes ``None`` and uses the
            ``--input`` path.
        output_stream: the text stream to write the JSON / summary
            to when ``--output`` is ``"-"``; defaults to
            ``sys.stdout``. Tests inject ``io.StringIO``.

    Returns:
        Process exit code: 0 on success, 2 on usage errors
        (missing keys, wrong shape, out-of-range threshold).
    """
    if output_stream is None:
        output_stream = sys.stdout

    # Read input. Three paths:
    # 1. ``input_stream`` explicitly provided (tests) — read from it.
    # 2. ``args.input == "-"`` — read from ``sys.stdin``.
    # 3. ``args.input`` is a filesystem path — open the file.
    try:
        if input_stream is not None:
            payload = json.loads(input_stream.read())
        elif args.input == "-":
            payload = json.loads(sys.stdin.read())
        else:
            with open(args.input, encoding="utf-8") as fh:
                payload = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"volunteer-dedup: invalid input: {exc}\n")
        return 2

    try:
        refs, threshold = _parse_input(payload)
    except ValueError as exc:
        sys.stderr.write(f"volunteer-dedup: invalid input: {exc}\n")
        return 2

    clusters = dedup_volunteers(refs, fuzzy_threshold=threshold)

    if args.summary:
        output_stream.write(_format_summary(clusters))
        return 0

    output_payload = {"clusters": [_cluster_to_dict(c) for c in clusters]}
    serialised = json.dumps(output_payload, ensure_ascii=False, indent=2, sort_keys=True)

    if args.output == "-":
        output_stream.write(serialised)
        output_stream.write("\n")
        return 0

    try:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(serialised)
            fh.write("\n")
    except OSError as exc:
        sys.stderr.write(f"volunteer-dedup: cannot write output: {exc}\n")
        return 5
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the ``python -m migration.cli_volunteer_dedup`` argument parser.

    Lives next to :func:`run_volunteer_dedup` so the operator
    surface stays discoverable from a single file (mirrors the
    pattern in ``migration.cli.build_parser``).
    """
    parser = argparse.ArgumentParser(
        prog="migration.cli_volunteer_dedup",
        description=(
            "Deduplicate free-text volunteer references from the legacy "
            "Access DB. Reads a JSON file of refs, writes a JSON file of "
            "clusters. Use --summary to print a one-line count breakdown "
            "instead of writing a file. Ambiguous clusters (decision = "
            "'needs_review') are the operator's manual-review surface."
        ),
    )
    parser.add_argument(
        "--input",
        required=True,
        help=(
            "Path to a JSON file with the shape "
            "{refs: [{name, source_table, source_row_id, dni?}, ...], "
            "fuzzy_threshold?: int}. Pass '-' to read from stdin."
        ),
    )
    parser.add_argument(
        "--output",
        default="-",
        help=(
            "Path to write the clusters JSON to. Pass '-' to write to "
            "stdout. Ignored when --summary is set (default: '-')."
        ),
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a one-line cluster-count breakdown instead of writing a file.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``python -m migration.cli_volunteer_dedup``."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return run_volunteer_dedup(args)


__all__ = [
    "build_parser",
    "main",
    "run_volunteer_dedup",
]


if __name__ == "__main__":
    raise SystemExit(main())

