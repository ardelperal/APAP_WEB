"""Strict TDD atoms for ``migration.cli_volunteer_dedup`` (issue #36).

The CLI bridge is a thin shell over the pure
:func:`migration.volunteer_dedup.dedup_volunteers` function: it
reads refs from JSON, runs the algorithm, and writes clusters to
JSON (or prints a one-line summary). These atoms pin the I/O
contract — input validation, output shape, summary line format —
without re-testing the algorithm itself (that lives in
``test_volunteer_dedup.py``).
"""

from __future__ import annotations

import io
import json

import pytest

from migration.cli_volunteer_dedup import (
    build_parser,
    run_volunteer_dedup,
)
from migration.volunteer_dedup import (
    DEFAULT_FUZZY_THRESHOLD,
)


def _write_input(payload: dict) -> io.StringIO:
    return io.StringIO(json.dumps(payload, ensure_ascii=False))


def test_summary_mode_prints_one_line_count_breakdown() -> None:
    """``--summary`` prints a one-line cluster-count breakdown.

    Format pinned: ``volunteer-dedup: status=ok total=N
    auto_merged=M needs_review=K unique=U`` so log scrapers and
    operator tooling can parse it without regex on free-form text.
    Mirrors the canonical ``apap-migrate`` line format
    (``status=...`` / ``reason=...``).
    """
    payload = {
        "refs": [
            {"name": "Maria Garcia", "source_table": "TbEntradas", "source_row_id": "e-1"},
            {"name": "Maria Garcia", "source_table": "TbAdopcion", "source_row_id": "a-1"},
            {"name": "Jon Smith", "source_table": "TbEntradas", "source_row_id": "e-2"},
        ]
    }
    args = build_parser().parse_args(
        ["--input", "unused.json", "--summary"]
    )
    output = io.StringIO()
    code = run_volunteer_dedup(
        args,
        input_stream=_write_input(payload),
        output_stream=output,
    )
    assert code == 0
    assert output.getvalue() == (
        "volunteer-dedup: status=ok total=2 auto_merged=1 needs_review=0 unique=1\n"
    )


def test_json_mode_writes_clusters_to_output_stream() -> None:
    """``--output -`` writes a JSON document to the output stream.

    The shape is ``{clusters: [...]}``; each cluster carries
    ``canonical_name``, ``dni``, ``decision``, ``reason``,
    ``confidence`` and ``sources``. No raw PII sanitisation is
    needed in the JSON (the operator has legitimate access).
    """
    payload = {
        "refs": [
            {"name": "Maria Garcia", "source_table": "TbEntradas", "source_row_id": "e-1"},
            {"name": "Maria Garcia", "source_table": "TbAdopcion", "source_row_id": "a-1"},
        ]
    }
    args = build_parser().parse_args(
        ["--input", "unused.json", "--output", "-"]
    )
    output = io.StringIO()
    code = run_volunteer_dedup(
        args,
        input_stream=_write_input(payload),
        output_stream=output,
    )
    assert code == 0
    parsed = json.loads(output.getvalue())
    assert "clusters" in parsed
    assert len(parsed["clusters"]) == 1
    cluster = parsed["clusters"][0]
    assert cluster["canonical_name"] == "Maria Garcia"
    assert cluster["decision"] == "auto_merged"
    assert cluster["reason"] == "exact_name_match"
    assert len(cluster["sources"]) == 2


def test_invalid_input_returns_exit_2() -> None:
    """Malformed input (missing ``refs`` key) returns exit code 2.

    Exit 2 is the canonical usage-error code in ``migration.cli``
    (``apap-migrate reconcile: …`` exits 2 on bad flags / bad
    timestamps). Keeping the same convention here means the
    operator's shell wrapper does not need to special-case the
    dedup subcommand.
    """
    payload: dict = {"not_refs": []}  # missing 'refs' key
    args = build_parser().parse_args(
        ["--input", "unused.json", "--summary"]
    )
    code = run_volunteer_dedup(
        args,
        input_stream=_write_input(payload),
        output_stream=io.StringIO(),
        # ``run_volunteer_dedup`` writes errors via ``sys.stderr``;
        # we monkeypatch it indirectly by using pytest's
        # ``capsys`` in the test body instead — see capsys read
        # below.
    )
    assert code == 2


def test_invalid_input_logs_to_stderr(capsys: pytest.CaptureFixture) -> None:
    """Malformed input writes a clear error message to stderr.

    The error line is greppable by the operator's shell wrapper
    without regex on free-form text. The prefix
    ``volunteer-dedup:`` mirrors ``apap-migrate`` so a wrapper
    that scrapes ``apap-*`` errors picks both up.
    """
    payload: dict = {"not_refs": []}
    args = build_parser().parse_args(
        ["--input", "unused.json", "--summary"]
    )
    code = run_volunteer_dedup(
        args,
        input_stream=_write_input(payload),
        output_stream=io.StringIO(),
    )
    captured = capsys.readouterr()
    assert code == 2
    assert captured.err.startswith("volunteer-dedup: invalid input")


def test_default_fuzzy_threshold_is_85() -> None:
    """When the input payload omits ``fuzzy_threshold`` the default
    is the algorithm's default (85).

    The constant is exported from ``migration.volunteer_dedup``
    so the CLI and the test both pin the same value; a future
    bump to the default has to update both the implementation
    and this atom.
    """
    assert DEFAULT_FUZZY_THRESHOLD == 85


def test_threshold_out_of_range_returns_exit_2() -> None:
    """A threshold outside ``[0, 100]`` is a usage error (exit 2)."""
    payload = {
        "refs": [],
        "fuzzy_threshold": 150,  # out of range
    }
    args = build_parser().parse_args(
        ["--input", "unused.json", "--summary"]
    )
    code = run_volunteer_dedup(
        args,
        input_stream=_write_input(payload),
        output_stream=io.StringIO(),
    )
    assert code == 2


def test_end_to_end_input_file_to_output_file(
    tmp_path,
) -> None:
    """End-to-end: read from a real file, write to a real file.

    Mirrors the operator workflow: a wrapper script extracts refs
    from the legacy tables, writes ``refs.json``, runs the CLI,
    and reads ``clusters.json``. This atom exercises that
    round-trip with a temp directory so the file paths are real
    but the contents are discarded.
    """
    input_path = tmp_path / "refs.json"
    output_path = tmp_path / "clusters.json"
    input_path.write_text(
        json.dumps(
            {
                "refs": [
                    {
                        "name": "Maria Garcia",
                        "source_table": "TbEntradas",
                        "source_row_id": "e-1",
                    },
                    {
                        "name": "Maria Garcia",
                        "source_table": "TbAdopcion",
                        "source_row_id": "a-1",
                    },
                    {
                        "name": "Jon Smith",
                        "source_table": "TbEntradas",
                        "source_row_id": "e-2",
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    args = build_parser().parse_args(
        [
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ]
    )
    code = run_volunteer_dedup(args)
    assert code == 0
    parsed = json.loads(output_path.read_text(encoding="utf-8"))
    assert len(parsed["clusters"]) == 2


# --- _cluster_to_dict helper (kept private but exercised for idempotence) -


def test_output_is_idempotent_double_run(tmp_path) -> None:
    """Two consecutive CLI runs on the same input produce byte-identical output.

    The pure algorithm is already idempotent (covered in
    ``test_volunteer_dedup.py::test_dedup_is_idempotent_double_run``);
    this atom re-asserts the property at the CLI layer — the JSON
    shape is sorted-keys + stable order so the byte-for-byte
    equality holds across runs.
    """
    input_path = tmp_path / "refs.json"
    input_path.write_text(
        json.dumps(
            {
                "refs": [
                    {
                        "name": "Maria Garcia",
                        "source_table": "TbEntradas",
                        "source_row_id": "e-1",
                    },
                    {
                        "name": "Maria Garcia",
                        "source_table": "TbAdopcion",
                        "source_row_id": "a-1",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    out_a = tmp_path / "a.json"
    out_b = tmp_path / "b.json"
    args_a = build_parser().parse_args(["--input", str(input_path), "--output", str(out_a)])
    args_b = build_parser().parse_args(["--input", str(input_path), "--output", str(out_b)])
    assert run_volunteer_dedup(args_a) == 0
    assert run_volunteer_dedup(args_b) == 0
    assert out_a.read_text(encoding="utf-8") == out_b.read_text(encoding="utf-8")

