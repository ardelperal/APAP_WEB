"""Tests for ``scripts/cosmic_ray_run_config.py`` (issue #545).

Stdlib-only plus the ``toml`` package (transitive dep of cosmic-ray;
already installed in CI's ``pip install -e ".[dev]"``). Runs on any
platform -- the script is exercised end-to-end on Linux by the CI
``mutation`` job itself, and these tests pin everything that can be
unit-checked without spawning cosmic-ray.
"""
from __future__ import annotations

import sqlite3
import textwrap
from pathlib import Path

import pytest

from scripts.cosmic_ray_run_config import (
    DEFAULT_SOCKET_TEMPLATE,
    DEFAULT_WORKER_COUNT,
    is_session_healthy,
    read_worker_urls,
    render_config,
    summarise_session,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def template_path(tmp_path: Path) -> Path:
    """Minimal cosmic-ray.toml shape that exercises the distributor rewrite."""
    text = textwrap.dedent(
        """\
        [cosmic-ray]
        module-path = ["app/foo.py"]
        timeout = 60.0
        excluded-modules = []
        test-command = "python -m pytest -x"

        [cosmic-ray.distributor]
        name = "local"

        [cosmic-ray.distributor.http]
        worker-urls = [
            "unix:///tmp/apap-cosmic-ray/w1.sock",
            "unix:///tmp/apap-cosmic-ray/w2.sock",
            "unix:///tmp/apap-cosmic-ray/w3.sock",
            "unix:///tmp/apap-cosmic-ray/w4.sock",
        ]

        [cosmic-ray.filters.operators-filter]
        exclude-operators = ["core/ReplaceBinaryOperator_BitOr_.*"]
        """
    )
    path = tmp_path / "cosmic-ray.toml"
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# render_config
# ---------------------------------------------------------------------------


def test_render_config_rewrites_worker_urls_to_per_run_dir(
    template_path: Path,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    out = render_config(template_path, run_dir)

    assert out == run_dir / "cosmic-ray.toml"
    rendered = out.read_text(encoding="utf-8")
    # Every worker URL points inside run_dir -- not at the template's
    # shared /tmp/apap-cosmic-ray/ path, which would collide across
    # concurrent runs (issue #545 body, in the context of #532). The
    # assertion uses ``as_posix()`` because cosmic-ray is Linux-only:
    # the helper writes whatever Python's ``str(Path)`` produces, and
    # the *shape* of the URL ("unix://<dir>/wN.sock") is what must hold
    # portably. Backslashes vs forward slashes are an OS detail below
    # this line.
    posix_run_dir = run_dir.as_posix()
    for i in range(1, DEFAULT_WORKER_COUNT + 1):
        assert f"unix://{posix_run_dir}/w{i}.sock" in rendered
    # The committed template's shared path must NOT survive the rewrite:
    assert "/tmp/apap-cosmic-ray/w" not in rendered


def test_render_config_switches_distributor_name_to_http(
    template_path: Path,
    tmp_path: Path,
) -> None:
    """The committed template defaults to ``local``; the per-run render flips it to ``http``."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    out = render_config(template_path, run_dir)

    import toml

    cfg = toml.loads(out.read_text(encoding="utf-8"))
    assert cfg["cosmic-ray"]["distributor"]["name"] == "http"


def test_render_config_preserves_unrelated_fields(
    template_path: Path,
    tmp_path: Path,
) -> None:
    """Only the distributor URL list is rewritten -- everything else passes through."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    out = render_config(template_path, run_dir)

    import toml

    cfg = toml.loads(out.read_text(encoding="utf-8"))
    assert cfg["cosmic-ray"]["module-path"] == ["app/foo.py"]
    assert cfg["cosmic-ray"]["timeout"] == 60.0
    assert cfg["cosmic-ray"]["test-command"] == "python -m pytest -x"
    assert cfg["cosmic-ray"]["filters"]["operators-filter"]["exclude-operators"] == [
        "core/ReplaceBinaryOperator_BitOr_.*"
    ]


def test_render_config_honours_worker_count(
    template_path: Path,
    tmp_path: Path,
) -> None:
    """Lower worker counts are the lever for the INCOMPETENT-ceiling tuning knob."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    out = render_config(template_path, run_dir, worker_count=2)
    import toml

    cfg = toml.loads(out.read_text(encoding="utf-8"))
    assert len(cfg["cosmic-ray"]["distributor"]["http"]["worker-urls"]) == 2
    assert cfg["cosmic-ray"]["distributor"]["http"]["worker-urls"] == [
        f"unix://{run_dir.as_posix()}/w1.sock",
        f"unix://{run_dir.as_posix()}/w2.sock",
    ]


def test_render_config_rejects_zero_or_negative_worker_count(
    template_path: Path,
    tmp_path: Path,
) -> None:
    """Worker count of 0 would mean no mutations ever execute -- a silent false-green."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    with pytest.raises(ValueError, match="worker_count must be >= 1"):
        render_config(template_path, run_dir, worker_count=0)


def test_render_config_requires_existing_run_dir(
    template_path: Path,
    tmp_path: Path,
) -> None:
    """Fail loud if the caller forgot ``mkdir -p`` -- cosmic-ray will not create it either."""
    with pytest.raises(FileNotFoundError, match="run_dir does not exist"):
        render_config(template_path, tmp_path / "missing")


# ---------------------------------------------------------------------------
# read_worker_urls
# ---------------------------------------------------------------------------


def test_read_worker_urls_round_trips_render_output(
    template_path: Path,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    out = render_config(template_path, run_dir)

    urls = read_worker_urls(out)
    assert urls == [
        DEFAULT_SOCKET_TEMPLATE.format(run_dir=run_dir.as_posix(), idx=i)
        for i in range(1, 5)
    ]


def test_read_worker_urls_returns_empty_for_local_distributor(tmp_path: Path) -> None:
    cfg = tmp_path / "cosmic-ray.toml"
    cfg.write_text(
        textwrap.dedent(
            """\
            [cosmic-ray]
            module-path = ["app/foo.py"]

            [cosmic-ray.distributor]
            name = "local"
            """
        ),
        encoding="utf-8",
    )
    assert read_worker_urls(cfg) == []


# ---------------------------------------------------------------------------
# summarise_session + is_session_healthy
# ---------------------------------------------------------------------------


def _populate_session(
    db: Path,
    *,
    killed: int,
    survived: int,
    incompetent: int,
    skipped: int,
    pending: int,
) -> None:
    """Build a cosmic-ray-shaped sqlite session with the given outcome mix.

    Mirrors the schema produced by ``cosmic-ray init`` so
    ``summarise_session`` can read it. Each row gets a unique ``job_id``
    and the matching ``work_results`` row (or no row at all for pending).
    """
    if db.exists():
        db.unlink()
    with sqlite3.connect(db) as connection:
        connection.executescript(
            """
            CREATE TABLE work_items (
                job_id TEXT PRIMARY KEY,
                worker_outcome TEXT,
                test_outcome TEXT
            );
            CREATE TABLE mutation_specs (
                job_id TEXT PRIMARY KEY,
                module_path TEXT,
                operator_name TEXT,
                occurrence INTEGER
            );
            CREATE TABLE work_results (
                job_id TEXT PRIMARY KEY,
                worker_outcome TEXT,
                test_outcome TEXT,
                output TEXT,
                diff TEXT
            );
            """
        )
        idx = 0
        for outcome, count in (
            ("killed", killed),
            ("survived", survived),
            ("incompetent", incompetent),
            ("skipped", skipped),
        ):
            for _ in range(count):
                idx += 1
                job_id = f"job-{idx}"
                connection.execute(
                    "INSERT INTO work_items (job_id, worker_outcome, test_outcome) "
                    "VALUES (?, ?, ?)",
                    (job_id, outcome.upper(), outcome.upper()),
                )
                connection.execute(
                    "INSERT INTO mutation_specs "
                    "(job_id, module_path, operator_name, occurrence) "
                    "VALUES (?, ?, ?, ?)",
                    (job_id, "app/foo.py", "core/ReplaceBinaryOperator_Add_0_0", 1),
                )
                connection.execute(
                    "INSERT INTO work_results (job_id, worker_outcome, test_outcome) "
                    "VALUES (?, ?, ?)",
                    (job_id, outcome.upper(), outcome.upper()),
                )
        # pending rows: queued work with no result row
        for _ in range(pending):
            idx += 1
            job_id = f"job-{idx}"
            connection.execute(
                "INSERT INTO work_items (job_id, worker_outcome, test_outcome) "
                "VALUES (?, NULL, NULL)",
                (job_id,),
            )
            connection.execute(
                "INSERT INTO mutation_specs "
                "(job_id, module_path, operator_name, occurrence) "
                "VALUES (?, ?, ?, ?)",
                (job_id, "app/foo.py", "core/ReplaceBinaryOperator_Add_0_0", 1),
            )
        connection.commit()


def test_summarise_session_reports_per_outcome_counts(tmp_path: Path) -> None:
    db = tmp_path / "session.sqlite"
    _populate_session(db, killed=129, survived=38, incompetent=0, skipped=66, pending=0)

    summary = summarise_session(db)

    # The 66 SKIPPED rows must NOT count toward total -- ``check_mutation.py``
    # treats them the same way (filtered before exec, not a real outcome).
    assert summary == {
        "total": 129 + 38,
        "killed": 129,
        "survived": 38,
        "incompetent": 0,
        "skipped": 66,
        "pending": 0,
    }


def test_summarise_session_rejects_missing_database(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="session database missing"):
        summarise_session(tmp_path / "nope.sqlite")


def test_is_session_healthy_accepts_a_real_run() -> None:
    summary = {
        "total": 167,
        "killed": 129,
        "survived": 38,
        "incompetent": 0,
        "skipped": 0,
        "pending": 0,
    }
    assert is_session_healthy(summary) is True


def test_is_session_healthy_rejects_pending() -> None:
    # An incomplete session is what cosmic-ray prints mid-run, not what
    # we want to gate on -- ``check_mutation.py`` rejects these too.
    summary = {
        "total": 167,
        "killed": 100,
        "survived": 38,
        "incompetent": 0,
        "skipped": 0,
        "pending": 29,
    }
    assert is_session_healthy(summary) is False


def test_is_session_healthy_rejects_incompetent_over_ceiling() -> None:
    # The 20 % ceiling is the exact threshold from scripts/check_mutation.py:
    # a run that crosses it is treated as a broken runner, not a code
    # regression. The check uses strict ``>`` (verified at
    # scripts/check_mutation.py:171), so the boundary is *inclusive* on
    # the healthy side: exactly 20 % is fine, 21 % is not.
    at_boundary = {
        "total": 100,
        "killed": 70,
        "survived": 10,
        "incompetent": 20,
        "skipped": 0,
        "pending": 0,
    }
    just_over = {
        "total": 100,
        "killed": 70,
        "survived": 10,
        "incompetent": 21,
        "skipped": 0,
        "pending": 0,
    }
    well_under = {
        "total": 100,
        "killed": 70,
        "survived": 10,
        "incompetent": 0,
        "skipped": 0,
        "pending": 0,
    }
    assert is_session_healthy(at_boundary) is True
    assert is_session_healthy(just_over) is False
    assert is_session_healthy(well_under) is True


def test_is_session_healthy_rejects_zero_killed() -> None:
    # ``check_mutation.py`` requires at least one KILLED, otherwise a
    # "100% survival" session could pass without exercising the suite at all.
    summary = {
        "total": 167,
        "killed": 0,
        "survived": 167,
        "incompetent": 0,
        "skipped": 0,
        "pending": 0,
    }
    assert is_session_healthy(summary) is False


def test_is_session_healthy_rejects_zero_total() -> None:
    # A session with no measurable rows (everything filtered) is the
    # exact failure mode ``check_mutation.py`` was written to flag.
    summary = {
        "total": 0,
        "killed": 0,
        "survived": 0,
        "incompetent": 0,
        "skipped": 0,
        "pending": 0,
    }
    assert is_session_healthy(summary) is False
