"""Tests for ``scripts/cosmic_ray_run_config.py`` (issue #545).

Stdlib-only -- the helper avoids the ``toml`` package on purpose so the
test stays portable and ``test_dev_dependencies.py``'s
``test_every_third_party_test_import_is_declared`` cannot flag this
test for an undeclared dependency. Runs on any platform; the script
is exercised end-to-end on Linux by the CI ``mutation`` job itself,
and these tests pin everything that can be unit-checked without
spawning cosmic-ray.
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
    """Minimal cosmic-ray.toml shape that exercises the http distributor rewrite.

    Mirrors the committed ``docs/quality/cosmic-ray.toml`` shape from
    the http-distributor era (PR #545) so the worker-URL rewrite path
    is exercised. Tests for the local distributor live in
    ``local_template_path`` + ``test_*_local_*`` below.
    """
    text = textwrap.dedent(
        """\
        # cosmic-ray configuration for the mutation gate (issue #431).

        [cosmic-ray]
        module-path = ["app/foo.py"]
        timeout = 60.0
        excluded-modules = []
        test-command = "python -m pytest -x"

        [cosmic-ray.distributor]
        name = "http"

        # Comment block above the http sub-section -- the helper must
        # preserve these comments when re-pointing the worker URLs.
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


@pytest.fixture()
def local_template_path(tmp_path: Path) -> Path:
    """Local-distributor shape: ``name = "local"``, no http sub-section.

    The committed template at HEAD uses this shape (rolled back from
    the http distributor per #434). The renderer must preserve
    ``name = "local"`` verbatim and skip the http block emission -- a
    regression in either direction would re-introduce the original
    bug (the script silently flipping the distributor) or break the
    pilot baseline (re-emitting a http block the template doesn't ask
    for).
    """
    text = textwrap.dedent(
        """\
        # cosmic-ray configuration for the mutation gate (issue #431).

        [cosmic-ray]
        module-path = ["app/foo.py"]
        timeout = 60.0
        excluded-modules = []
        test-command = "python -m pytest -x"

        [cosmic-ray.distributor]
        name = "local"

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
    # The committed template's placeholder URL list must NOT survive the
    # rewrite. Search for the exact quoted form (not the bare substring
    # "apap-cosmic-ray/w") so the test is not confused by the file's
    # own header comment that mentions the same path as historical
    # context.
    for i in range(1, 5):
        assert f'"unix:///tmp/apap-cosmic-ray/w{i}.sock"' not in rendered


def test_render_config_preserves_distributor_name_from_template(
    template_path: Path,
    tmp_path: Path,
) -> None:
    """The helper preserves whatever ``name =`` the template declared.

    Earlier revisions of this script hard-coded ``name = "http"`` regardless
    of what the template asked for, on the assumption that the CI only ever
    ran the http distributor (#545). Once the workflow reverts to the local
    distributor (the CI's actual state per #434), that hard-code silently
    overrides the operator's choice and ``cosmic-ray exec`` re-enters the
    broken http distributor path. The renderer must now mirror the
    template verbatim; a regression here is the original bug coming back.
    """
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    out = render_config(template_path, run_dir)

    rendered = out.read_text(encoding="utf-8")
    # The template declares ``name = "http"``; the rendered file must
    # carry that exact line, with no ``local`` injected anywhere.
    assert 'name = "http"' in rendered
    assert 'name = "local"' not in rendered


def test_render_config_local_template_omits_http_block(
    local_template_path: Path,
    tmp_path: Path,
) -> None:
    """Local distributor templates do not get a synthesised http sub-section.

    The http block rewrite is only meaningful when the template asked for
    the http distributor; emitting it for a local template would re-introduce
    the broken unix:// URL scheme into the rendered config that cosmic-ray
    would then try to dispatch against.
    """
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    out = render_config(local_template_path, run_dir)

    rendered = out.read_text(encoding="utf-8")
    # Local distributor stays verbatim.
    assert 'name = "local"' in rendered
    # No http sub-section synthesised -- aiohttp in cosmic-ray 8.4.6
    # rejects unix:// URLs and the local distributor needs no workers
    # at all.
    assert "[cosmic-ray.distributor.http]" not in rendered
    assert "worker-urls" not in rendered


def test_render_config_preserves_unrelated_fields_and_comments(
    template_path: Path,
    tmp_path: Path,
) -> None:
    """Only the distributor URL list is rewritten -- everything else passes through."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    out = render_config(template_path, run_dir)

    rendered = out.read_text(encoding="utf-8")
    # Unrelated fields survive the rewrite verbatim.
    assert 'module-path = ["app/foo.py"]' in rendered
    assert "timeout = 60.0" in rendered
    assert 'test-command = "python -m pytest -x"' in rendered
    assert 'exclude-operators = ["core/ReplaceBinaryOperator_BitOr_.*"]' in rendered
    # The leading file comment (cosmic-ray configuration for the
    # mutation gate ...) must survive -- the operator added it as
    # historical context and a TOML round-trip would silently strip it.
    assert "cosmic-ray configuration for the mutation gate" in rendered
    # The "Comment block above the http sub-section" comment in the
    # template must also survive -- the line-based rewrite only touches
    # the lines inside the [cosmic-ray.distributor] block, not the
    # comments that immediately precede it.
    assert "Comment block above the http sub-section" in rendered


def test_render_config_honours_worker_count(
    template_path: Path,
    tmp_path: Path,
) -> None:
    """Lower worker counts are the lever for the INCOMPETENT-ceiling tuning knob."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    out = render_config(template_path, run_dir, worker_count=2)

    rendered = out.read_text(encoding="utf-8")
    # Use the exact quoted form so the assertion does not match the
    # historical-context mention of ``w3.sock`` in the file's own header
    # comment. The point of the check is that the synthesised
    # ``worker-urls = [...]`` list contains exactly two entries; the
    # fourth-entry URL string is the cleanest way to assert that.
    assert '"unix://' in rendered and "w1.sock" in rendered
    assert "w2.sock" in rendered
    assert '"unix:///tmp/apap-cosmic-ray/w3.sock"' not in rendered
    assert '"unix:///tmp/apap-cosmic-ray/w4.sock"' not in rendered
    # The synthesised list ends with the second worker URL and the
    # closing ``]``; verify the count is exactly 2 entries by counting
    # the worker-urls opening.
    assert rendered.count("worker-urls = [") == 1


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


def test_render_config_rejects_template_without_distributor_section(
    tmp_path: Path,
) -> None:
    """A template missing the ``[cosmic-ray.distributor]`` block must fail loudly.

    Without this branch a typo'd template path or a botched upstream
    edit would render a config that cosmic-ray still parses but with
    ``distributor.name = "local"`` -- the exact regression this whole
    change exists to undo.
    """
    template = tmp_path / "cosmic-ray.toml"
    template.write_text(
        textwrap.dedent(
            """\
            [cosmic-ray]
            module-path = ["app/foo.py"]
            """
        ),
        encoding="utf-8",
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    with pytest.raises(ValueError, match="does not contain a \\[cosmic-ray.distributor\\]"):
        render_config(template, run_dir)


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
