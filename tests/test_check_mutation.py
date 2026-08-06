"""Tests for the mutation-score ratchet and its degenerate-run guard (#431).

Sessions are built synthetically with ``sqlite3`` so the gate is verified on
every platform, including the ones where cosmic-ray itself cannot execute
mutants. That independence is the point: the guard exists precisely because a
broken runner reports a passing score.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts.check_mutation import (
    MAX_INCOMPETENT_RATIO,
    check_ratchet,
    check_run_health,
    load_baseline,
    main,
    measure_survivors,
    read_session,
)

_SCHEMA = """
CREATE TABLE work_items (job_id TEXT PRIMARY KEY);
CREATE TABLE mutation_specs (
    module_path TEXT,
    operator_name TEXT,
    job_id TEXT PRIMARY KEY
);
CREATE TABLE work_results (
    worker_outcome TEXT,
    test_outcome TEXT,
    job_id TEXT PRIMARY KEY
);
"""


def make_session(
    path: Path,
    jobs: list[tuple[str, str | None]],
    *,
    skipped: list[str] | None = None,
) -> Path:
    """Write a cosmic-ray-shaped session.

    ``jobs`` is a list of ``(module_path, test_outcome)``. A ``None`` outcome
    models a queued job that never produced a result. ``skipped`` adds modules
    whose mutants were filtered out by ``cr-filter-operators``: those carry
    ``worker_outcome = SKIPPED`` and a NULL ``test_outcome``.
    """
    connection = sqlite3.connect(path)
    try:
        connection.executescript(_SCHEMA)
        for index, (module_path, outcome) in enumerate(jobs):
            job_id = f"job-{index}"
            connection.execute("INSERT INTO work_items VALUES (?)", (job_id,))
            connection.execute(
                "INSERT INTO mutation_specs VALUES (?, ?, ?)",
                (module_path, "core/ReplaceComparisonOperator_Lt_Gt", job_id),
            )
            if outcome is not None:
                connection.execute(
                    "INSERT INTO work_results VALUES (?, ?, ?)",
                    ("NORMAL", outcome, job_id),
                )
        for index, module_path in enumerate(skipped or []):
            job_id = f"skipped-{index}"
            connection.execute("INSERT INTO work_items VALUES (?)", (job_id,))
            connection.execute(
                "INSERT INTO mutation_specs VALUES (?, ?, ?)",
                (module_path, "core/ReplaceBinaryOperator_BitOr_Add", job_id),
            )
            connection.execute(
                "INSERT INTO work_results VALUES (?, ?, ?)",
                ("SKIPPED", None, job_id),
            )
        connection.commit()
    finally:
        connection.close()
    return path


# --- read_session ----------------------------------------------------------


def test_read_session_missing_file_is_an_error(tmp_path: Path) -> None:
    rows, errors = read_session(tmp_path / "absent.sqlite")
    assert rows == []
    assert "session file not found" in errors[0]


def test_read_session_normalizes_sqlalchemy_enum_names(tmp_path: Path) -> None:
    """SQLAlchemy stores the member NAME; TestOutcome's value is lowercase."""
    session = make_session(
        tmp_path / "s.sqlite",
        [("app/m.py", "KILLED"), ("app/m.py", "survived")],
    )
    rows, errors = read_session(session)
    assert errors == []
    assert [row["test_outcome"] for row in rows] == ["killed", "survived"]


def test_read_session_normalizes_windows_module_paths(tmp_path: Path) -> None:
    """cosmic-ray records `app\\m.py` on Windows; the baseline is POSIX."""
    session = make_session(tmp_path / "s.sqlite", [("app\\modules\\m.py", "KILLED")])
    rows, _ = read_session(session)
    assert rows[0]["module_path"] == "app/modules/m.py"


# --- check_run_health: the degenerate-run guard ----------------------------


def test_health_rejects_empty_session() -> None:
    violations = check_run_health([])
    assert len(violations) == 1
    assert "no mutation jobs" in violations[0]


def test_health_rejects_incomplete_session(tmp_path: Path) -> None:
    session = make_session(
        tmp_path / "s.sqlite",
        [("app/m.py", "KILLED"), ("app/m.py", None)],
    )
    rows, _ = read_session(session)
    violations = check_run_health(rows)
    assert "incomplete" in violations[0]
    assert "1/2" in violations[0]


def test_health_rejects_all_incompetent_run(tmp_path: Path) -> None:
    """The measured native-Windows failure mode: 27/27 INCOMPETENT, rate 0.00.

    ``cr-rate`` reports a passing 0.00 for exactly this session. The guard is
    what turns it into a failure.
    """
    session = make_session(tmp_path / "s.sqlite", [("app/m.py", "INCOMPETENT")] * 27)
    rows, _ = read_session(session)
    violations = check_run_health(rows)

    assert any("INCOMPETENT" in v and "runner is broken" in v for v in violations)
    assert any("0/27 mutants were killed" in v for v in violations)


def test_health_accepts_a_few_incompetent_mutants(tmp_path: Path) -> None:
    """Some incompetent mutants are normal; the ceiling is a ratio, not zero."""
    jobs = [("app/m.py", "INCOMPETENT")] * 2 + [("app/m.py", "KILLED")] * 18
    session = make_session(tmp_path / "s.sqlite", jobs)
    rows, _ = read_session(session)
    assert check_run_health(rows) == []


def test_health_ceiling_is_exclusive_at_the_documented_ratio(tmp_path: Path) -> None:
    """Exactly at the ceiling passes; one more mutant over it fails."""
    at_ceiling = int(MAX_INCOMPETENT_RATIO * 20)
    jobs = [("app/m.py", "INCOMPETENT")] * at_ceiling
    jobs += [("app/m.py", "KILLED")] * (20 - at_ceiling)
    session = make_session(tmp_path / "at.sqlite", jobs)
    rows, _ = read_session(session)
    assert check_run_health(rows) == []

    over = [("app/m.py", "INCOMPETENT")] * (at_ceiling + 1)
    over += [("app/m.py", "KILLED")] * (20 - at_ceiling - 1)
    session = make_session(tmp_path / "over.sqlite", over)
    rows, _ = read_session(session)
    assert any("runner is broken" in v for v in check_run_health(rows))


def test_health_rejects_a_run_that_killed_nothing(tmp_path: Path) -> None:
    """All-survived is a real score, but zero kills means the suite never ran."""
    session = make_session(tmp_path / "s.sqlite", [("app/m.py", "SURVIVED")] * 10)
    rows, _ = read_session(session)
    violations = check_run_health(rows)
    assert any("0/10 mutants were killed" in v for v in violations)


# --- filtered (SKIPPED) mutants --------------------------------------------


def test_filtered_mutants_do_not_make_a_session_look_incomplete(
    tmp_path: Path,
) -> None:
    """cr-filter-operators leaves SKIPPED rows with a NULL test_outcome.

    Treating those as pending work would fail every filtered session — the
    regression this test exists to prevent.
    """
    session = make_session(
        tmp_path / "s.sqlite",
        [("app/m.py", "KILLED")] * 10,
        skipped=["app/m.py"] * 66,
    )
    rows, _ = read_session(session)
    assert len(rows) == 76
    assert check_run_health(rows) == []


def test_filtered_mutants_are_excluded_from_the_incompetent_ratio(
    tmp_path: Path,
) -> None:
    """A skipped mutant is not evidence of a broken runner."""
    session = make_session(
        tmp_path / "s.sqlite",
        [("app/m.py", "KILLED")] * 10,
        skipped=["app/m.py"] * 90,
    )
    rows, _ = read_session(session)
    assert check_run_health(rows) == []


def test_filtered_mutants_are_not_counted_as_survivors(tmp_path: Path) -> None:
    session = make_session(
        tmp_path / "s.sqlite",
        [("app/m.py", "SURVIVED"), ("app/m.py", "KILLED")],
        skipped=["app/m.py"] * 66,
    )
    rows, _ = read_session(session)
    assert measure_survivors(rows) == {"app/m.py": 1}


def test_a_fully_filtered_session_is_rejected(tmp_path: Path) -> None:
    """An over-broad exclude-operators list must not read as a clean run."""
    session = make_session(tmp_path / "s.sqlite", [], skipped=["app/m.py"] * 20)
    rows, _ = read_session(session)
    violations = check_run_health(rows)
    assert any("filtered out" in v for v in violations)


# --- measure_survivors -----------------------------------------------------


def test_measure_survivors_counts_per_module(tmp_path: Path) -> None:
    session = make_session(
        tmp_path / "s.sqlite",
        [
            ("app/a.py", "SURVIVED"),
            ("app/a.py", "KILLED"),
            ("app/a.py", "SURVIVED"),
            ("app/b.py", "KILLED"),
        ],
    )
    rows, _ = read_session(session)
    assert measure_survivors(rows) == {"app/a.py": 2, "app/b.py": 0}


# --- check_ratchet ---------------------------------------------------------


def test_ratchet_passes_when_survivors_match_baseline() -> None:
    violations, notices = check_ratchet({"app/a.py": 3}, {"app/a.py": 3})
    assert violations == []
    assert notices == []


def test_ratchet_fails_when_survivors_grow() -> None:
    violations, _ = check_ratchet({"app/a.py": 4}, {"app/a.py": 3})
    assert "grew beyond its baseline of 3" in violations[0]


def test_ratchet_notices_improvement_without_failing() -> None:
    violations, notices = check_ratchet({"app/a.py": 1}, {"app/a.py": 3})
    assert violations == []
    assert "lower the entry in the same PR" in notices[0]


def test_ratchet_rejects_unpinned_module() -> None:
    violations, _ = check_ratchet({"app/new.py": 2}, {})
    assert "no baseline entry" in violations[0]


def test_ratchet_rejects_stale_baseline_entry() -> None:
    violations, _ = check_ratchet({}, {"app/gone.py": 1})
    assert "stale baseline entry" in violations[0]


# --- load_baseline ---------------------------------------------------------


def test_load_baseline_reads_modules(tmp_path: Path) -> None:
    path = tmp_path / "b.json"
    path.write_text(json.dumps({"modules": {"app/a.py": 2}}), encoding="utf-8")
    modules, errors = load_baseline(path)
    assert errors == []
    assert modules == {"app/a.py": 2}


def test_load_baseline_reports_malformed_json(tmp_path: Path) -> None:
    path = tmp_path / "b.json"
    path.write_text("{not json", encoding="utf-8")
    _, errors = load_baseline(path)
    assert "cannot read baseline" in errors[0]


# --- main ------------------------------------------------------------------


def test_main_fails_on_degenerate_run_before_reading_baseline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ordering matters: a broken run fails even with no baseline on disk."""
    session = make_session(tmp_path / "s.sqlite", [("app/m.py", "INCOMPETENT")] * 27)
    exit_code = main([str(session), "--baseline", str(tmp_path / "absent.json")])
    assert exit_code == 1
    assert "run not trustworthy" in capsys.readouterr().out


def test_main_emit_baseline_prints_measured_survivors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    session = make_session(
        tmp_path / "s.sqlite",
        [("app/a.py", "SURVIVED"), ("app/a.py", "KILLED")],
    )
    assert main([str(session), "--emit-baseline"]) == 0
    assert json.loads(capsys.readouterr().out) == {"modules": {"app/a.py": 1}}


def test_main_passes_on_a_healthy_pinned_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    session = make_session(
        tmp_path / "s.sqlite",
        [("app/a.py", "SURVIVED")] + [("app/a.py", "KILLED")] * 9,
    )
    baseline = tmp_path / "b.json"
    baseline.write_text(json.dumps({"modules": {"app/a.py": 1}}), encoding="utf-8")

    assert main([str(session), "--baseline", str(baseline)]) == 0
    assert "check_mutation: OK" in capsys.readouterr().out
