"""Tests for the mutation-score ratchet and its degenerate-run guard (#431).

Sessions are built synthetically with ``sqlite3`` so the gate is verified on
every platform, including the ones where cosmic-ray itself cannot execute
mutants. That independence is the point: the guard exists precisely because a
broken runner reports a passing score.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta  # noqa: F401  (timedelta used in tests below)
from pathlib import Path

import pytest

from scripts.check_mutation import (
    GRACE_PERIOD_DAYS,
    MAX_INCOMPETENT_RATIO,
    check_pending_overdue,
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


def test_ratchet_ignores_awaiting_acquisition_modules() -> None:
    """Issue #434: a module added with an ``awaiting_acquisition`` marker must
    not raise "no baseline entry" when measured. Its overdue-ness is enforced
    separately by ``check_pending_overdue``.
    """
    violations, notices = check_ratchet(
        {"app/adopciones/service.py": 5},
        {},
        {"app/adopciones/service.py": "2026-08-06"},
    )
    assert violations == []
    assert notices == []


# --- check_pending_overdue --------------------------------------------------


def test_pending_entry_within_grace_period_passes() -> None:
    """Issue #434: a fresh awaiting_acquisition entry is silent.

    The grace gives the scheduled CI ``mutation`` job time to acquire the
    real number; it must not raise a red flag during that window.
    """
    today = date(2026, 8, 6)
    violations = check_pending_overdue(
        {"app/adopciones/service.py": "2026-08-06"},
        today,
    )
    assert violations == []


def test_pending_entry_exactly_at_grace_period_passes() -> None:
    """``> grace_period_days`` is overdue; ``== grace_period_days`` is not."""
    today = date(2026, 8, 6) + timedelta(days=GRACE_PERIOD_DAYS)
    violations = check_pending_overdue(
        {"app/adopciones/service.py": "2026-08-06"},
        today,
    )
    assert violations == []


def test_pending_entry_one_day_past_grace_fails_with_a_clear_message() -> None:
    today = date(2026, 8, 6) + timedelta(days=GRACE_PERIOD_DAYS + 1)
    violations = check_pending_overdue(
        {"app/adopciones/service.py": "2026-08-06"},
        today,
    )
    assert len(violations) == 1
    assert "app/adopciones/service.py" in violations[0]
    assert f"{GRACE_PERIOD_DAYS}-day grace period" in violations[0]
    assert "scheduled CI mutation job" in violations[0]


def test_pending_entry_far_past_grade_reports_the_age() -> None:
    today = date(2026, 8, 6) + timedelta(days=100)
    violations = check_pending_overdue(
        {"app/adopciones/service.py": "2026-08-06"},
        today,
    )
    assert "100 days old" in violations[0]


def test_pending_entry_with_invalid_iso_date_fails() -> None:
    """An unparseable date is treated as overdue; it cannot stay silent."""
    violations = check_pending_overdue(
        {"app/x.py": "yesterday-ish"},
        date(2026, 8, 6),
    )
    assert "not a valid ISO date" in violations[0]


def test_pending_overdue_with_empty_map_passes() -> None:
    violations = check_pending_overdue({}, date(2026, 8, 6))
    assert violations == []


# --- load_baseline ---------------------------------------------------------


def test_load_baseline_reads_modules(tmp_path: Path) -> None:
    path = tmp_path / "b.json"
    path.write_text(json.dumps({"modules": {"app/a.py": 2}}), encoding="utf-8")
    modules, awaiting, errors = load_baseline(path)
    assert errors == []
    assert modules == {"app/a.py": 2}
    assert awaiting == {}


def test_load_baseline_reports_malformed_json(tmp_path: Path) -> None:
    path = tmp_path / "b.json"
    path.write_text("{not json", encoding="utf-8")
    _, _, errors = load_baseline(path)
    assert "cannot read baseline" in errors[0]


def test_load_baseline_reads_awaiting_acquisition(tmp_path: Path) -> None:
    """Issue #434: pending entries live in a separate map, not under modules."""
    payload = {
        "modules": {"app/a.py": 2},
        "awaiting_acquisition": {"app/b.py": "2026-08-06"},
    }
    path = tmp_path / "b.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    modules, awaiting, errors = load_baseline(path)
    assert errors == []
    assert modules == {"app/a.py": 2}
    assert awaiting == {"app/b.py": "2026-08-06"}


def test_load_baseline_rejects_non_object_awaiting_acquisition(tmp_path: Path) -> None:
    """A list under awaiting_acquisition is a structural defect; the file is rejected."""
    path = tmp_path / "b.json"
    path.write_text(json.dumps({"awaiting_acquisition": ["bad"]}), encoding="utf-8")
    _, _, errors = load_baseline(path)
    assert "'awaiting_acquisition' must be an object" in errors[0]


def test_load_baseline_rejects_non_int_module_values(tmp_path: Path) -> None:
    """A string under modules is a structural defect; the file is rejected.

    Without this guard a future contributor could silently turn a real
    measurement into a malformed file and the ratchet would either crash on
    ``int(value)`` or compare strings. Either way the gate stops being
    deterministic (§34.3).
    """
    path = tmp_path / "b.json"
    path.write_text(json.dumps({"modules": {"app/a.py": "two"}}), encoding="utf-8")
    _, _, errors = load_baseline(path)
    assert "'modules' contains non-int values" in errors[0]


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


def test_main_passes_when_pending_module_is_measured_within_grace(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue #434: end-to-end pass when the new module has been measured.

    Simulates the first scheduled CI mutation run after the PR lands: the
    session covers both the pilot and the new module, the baseline pins the
    pilot and marks the new one as awaiting acquisition, and ``main`` reports
    OK without raising "no baseline entry" for the pending module.
    """
    today = date.today()
    since = (today - timedelta(days=GRACE_PERIOD_DAYS - 1)).isoformat()

    jobs = (
        [("migration/derivation.py", "KILLED")] * 10
        + [("app/modules/adopciones/service.py", "KILLED")] * 10
    )
    session = make_session(tmp_path / "s.sqlite", jobs)

    baseline = tmp_path / "b.json"
    baseline.write_text(
        json.dumps(
            {
                "modules": {"migration/derivation.py": 0},
                "awaiting_acquisition": {
                    "app/modules/adopciones/service.py": since,
                },
            }
        ),
        encoding="utf-8",
    )

    import scripts.check_mutation as cm

    class _FrozenDate(date):
        @classmethod
        def today(cls) -> _FrozenDate:
            return _FrozenDate.fromisoformat(today.isoformat())

    monkeypatch.setattr(cm, "date", _FrozenDate)

    assert main([str(session), "--baseline", str(baseline)]) == 0
    out = capsys.readouterr().out
    assert "check_mutation: OK" in out
    assert "1 awaiting acquisition" in out


def test_main_fails_when_pending_module_overdue(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue #434: end-to-end fail when the scheduled run never acquires.

    The grace period expired and ``awaiting_acquisition`` is still on disk;
    the ratchet must surface that with the §32.P3 message and exit 1.
    """
    today = date.today()
    since = (today - timedelta(days=GRACE_PERIOD_DAYS + 5)).isoformat()

    jobs = [("migration/derivation.py", "KILLED")] * 10
    session = make_session(tmp_path / "s.sqlite", jobs)

    baseline = tmp_path / "b.json"
    baseline.write_text(
        json.dumps(
            {
                "modules": {"migration/derivation.py": 0},
                "awaiting_acquisition": {
                    "app/modules/adopciones/service.py": since,
                },
            }
        ),
        encoding="utf-8",
    )

    import scripts.check_mutation as cm

    class _FrozenDate(date):
        @classmethod
        def today(cls) -> _FrozenDate:
            return _FrozenDate.fromisoformat(today.isoformat())

    monkeypatch.setattr(cm, "date", _FrozenDate)

    assert main([str(session), "--baseline", str(baseline)]) == 1
    out = capsys.readouterr().out
    assert "FAIL: app/modules/adopciones/service.py: awaiting_acquisition marker" in out
    assert f"{GRACE_PERIOD_DAYS}-day grace period" in out
