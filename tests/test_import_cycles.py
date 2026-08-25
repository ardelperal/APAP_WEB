"""Pin the import-cycle detector (issue #443)."""
from __future__ import annotations

import contextlib
import importlib.util
import io
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = REPO_ROOT / "scripts" / "check_import_cycles.py"


def _load_checker():
    spec = importlib.util.spec_from_file_location(
        "check_import_cycles", CHECKER_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextlib.contextmanager
def _tmp_source(source: str):
    """Write ``source`` to a temp .py file and yield its Path.

    On Windows the file is held by the antivirus / indexer for a moment
    after ``mkstemp`` returns; the unlink can fail with WinError 32.
    The temp dir is wiped at session end so we skip the cleanup here.
    """
    import tempfile

    fd, name = tempfile.mkstemp(suffix=".py")
    Path(name).write_text(source, encoding="utf-8")
    yield Path(name)


def test_baseline_entries_are_valid_tuples() -> None:
    """Every BASELINE key is a non-empty tuple of module strings.

    A stale entry that no longer matches a real cycle is silent
    headroom: a follow-up could re-introduce the cycle for free.
    test_baseline_entries_are_still_real_cycles below catches that.
    Here we only check the structural contract.
    """
    checker = _load_checker()

    for key, reason in checker.BASELINE.items():
        assert isinstance(key, tuple)
        assert len(key) >= 2
        assert reason
        assert all(isinstance(m, str) for m in key)


def test_baseline_entries_are_still_real_cycles() -> None:
    """BASELINE may not accumulate stale entries.

    A baselined cycle that no longer exists is silent headroom: the
    same forbidden import could come back for free. ``check`` reports
    each stale entry as a notice, so the baseline must produce none
    against the real tree.
    """
    checker = _load_checker()

    _violations, notices = checker.check(REPO_ROOT)

    assert notices == [], (
        "stale BASELINE entries in scripts/check_import_cycles.py -- the cycle "
        "is fixed, so delete the entry to lock in the improvement"
    )


def test_tarjan_finds_simple_cycle() -> None:
    checker = _load_checker()
    graph = {"a": {"b"}, "b": {"a"}}
    sccs = checker._tarjan_sccs(graph)
    assert len(sccs) == 1
    assert checker._cycle_key(sccs[0]) == ("a", "b")


def test_tarjan_no_cycles() -> None:
    checker = _load_checker()
    graph = {"a": {"b"}, "b": {"c"}, "c": set()}
    sccs = checker._tarjan_sccs(graph)
    assert sccs == []


def test_tarjan_three_node_cycle() -> None:
    checker = _load_checker()
    graph = {"a": {"b"}, "b": {"c"}, "c": {"a"}}
    sccs = checker._tarjan_sccs(graph)
    assert len(sccs) == 1
    assert checker._cycle_key(sccs[0]) == ("a", "b", "c")


def test_tarjan_ignores_singletons_and_self_loops() -> None:
    """Self-loops are not cycles; only SCCs of size > 1 are reported."""
    checker = _load_checker()
    graph = {"a": {"a"}, "b": {"c"}, "c": {"b"}}
    sccs = checker._tarjan_sccs(graph)
    assert len(sccs) == 1
    assert checker._cycle_key(sccs[0]) == ("b", "c")


def test_extract_imports_filters_non_app() -> None:
    """Non-app imports (stdlib, third-party) are dropped.

    ``_extract_imports`` reports the package-level module of an
    ``ImportFrom`` (e.g. ``app.modules.tasks``), not the submodule
    name (``app.modules.tasks.service``); that is enough to build the
    cycle graph, where the edge is between modules.
    """
    checker = _load_checker()
    with _tmp_source(
        "import os\n"
        "import sys\n"
        "import app.core.config\n"
        "from app.modules.tasks import service\n"
    ) as path:
        imports = checker._extract_imports(path)
    assert "app.core.config" in imports
    assert "app.modules.tasks" in imports
    assert "os" not in imports
    assert "sys" not in imports


def test_check_reports_baseline_as_notice(tmp_path: Path) -> None:
    """A cycle in the baseline produces zero violations and zero notices.

    Notices are reserved for the OPPOSITE: a baseline entry that no
    longer matches a real cycle (stale entry, delete to lock in the
    fix). A cycle that is in baseline AND still present is silent on
    purpose -- it is intentional and known, not a regression.
    """
    checker = _load_checker()
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "a.py").write_text(
        "from app.b import thing\n", encoding="utf-8"
    )
    (app_dir / "b.py").write_text(
        "from app.a import other\n", encoding="utf-8"
    )
    baseline = {("app.a", "app.b"): "known"}
    violations, notices = checker.check(tmp_path, baseline)
    assert violations == []
    assert notices == []


def test_check_reports_stale_baseline_as_notice(tmp_path: Path) -> None:
    """A baseline entry with no matching cycle in the tree is a notice."""
    checker = _load_checker()
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "a.py").write_text("x = 1\n", encoding="utf-8")
    baseline = {("app.a", "app.b"): "stale"}
    violations, notices = checker.check(tmp_path, baseline)
    assert violations == []
    assert any("no longer a cycle" in n for n in notices)


def test_check_reports_new_cycle_as_violation(tmp_path: Path) -> None:
    """A cycle not in the baseline is reported as a violation."""
    checker = _load_checker()
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "x.py").write_text(
        "from app.y import thing\n", encoding="utf-8"
    )
    (app_dir / "y.py").write_text(
        "from app.x import other\n", encoding="utf-8"
    )
    violations, notices = checker.check(tmp_path, {})
    assert any("NEW" in v for v in violations)


def test_current_tree_passes_with_baseline() -> None:
    """The checker exits 0 on the repository as it stands.

    Every cycle that predates the rule must be in BASELINE -- otherwise
    the gate would be born red and get deleted within a week. Sister of
    tests/test_layers.py::test_current_tree_passes_with_baseline.
    """
    checker = _load_checker()
    assert checker.main([str(REPO_ROOT)]) == 0


def test_emit_baseline_prints_dict_block() -> None:
    """``--emit-baseline`` prints a copy-pasteable BASELINE block."""
    checker = _load_checker()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = checker.main(["--emit-baseline", str(REPO_ROOT)])
    assert rc == 0
    output = buf.getvalue()
    assert output.startswith("BASELINE = {")
    assert output.rstrip().endswith("}")
    assert "cycle frozen at this commit" in output


def test_main_returns_nonzero_on_violation(tmp_path: Path) -> None:
    """``main()`` exits 1 when the tree holds a cycle not in BASELINE."""
    checker = _load_checker()
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "m.py").write_text(
        "from app.n import thing\n", encoding="utf-8"
    )
    (app_dir / "n.py").write_text(
        "from app.m import other\n", encoding="utf-8"
    )
    assert checker.main([str(tmp_path)]) == 1
