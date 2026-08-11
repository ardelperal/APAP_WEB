"""The test suite may only import what ``[dev]`` declares (issue #526).

``tests/test_security_scanning.py`` imports ``yaml`` to parse the workflow files and enforce
Hard Rule 15. ``pyyaml`` was declared only in the ``[etl]`` extra, and CI installs ``[dev]``,
so the import survived purely as a transitive dependency of ``djlint``, ``libcst`` and
``xenon``. None of the three promises to keep carrying it. The day one drops it, that file
fails at collection and the runner gate goes down with it.

Declaring the dependency fixes that one import. This gate fixes the class: a test may not
import a third-party module the project never asked for.
"""
from __future__ import annotations

import ast
import sys
import tomllib
from importlib.metadata import packages_distributions
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = REPO_ROOT / "tests"
SCRIPTS_DIR = REPO_ROOT / "scripts"
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"

#: Import roots that are this repository's own code, not a distribution.
FIRST_PARTY = frozenset({"app", "migration", "scripts", "tests", "conftest"})


def _normalise(name: str) -> str:
    """PEP 503 name normalisation, enough for comparing declared to installed."""
    return name.lower().replace("_", "-").replace(".", "-")


def declared_distributions() -> set[str]:
    """Every distribution the runtime and the ``dev`` extra declare, normalised."""
    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    project = data["project"]
    specs = list(project.get("dependencies", []))
    specs += project["optional-dependencies"]["dev"]
    names = set()
    for spec in specs:
        # Strip extras and any version specifier: `pytest-cov[toml]>=5.0` -> `pytest-cov`.
        head = spec.split(";")[0].split("[")[0]
        for separator in (">", "<", "=", "!", "~"):
            head = head.split(separator)[0]
        names.add(_normalise(head.strip()))
    return names


def _is_first_party(module: str) -> bool:
    """True for this repo's own modules, including the ``scripts/`` ones tests sys.path in.

    Several gate tests append ``scripts/`` to ``sys.path`` and import the gate directly
    (``import check_workflows``). Those roots resolve to a file in this repository, not to a
    distribution, so they are first-party however they look to ``importlib``.
    """
    if module in FIRST_PARTY or module.startswith("_"):
        return True
    return (SCRIPTS_DIR / f"{module}.py").is_file() or (SCRIPTS_DIR / module).is_dir()


def _imported_roots() -> dict[str, set[str]]:
    """Map each top-level import root under ``tests/`` to the files importing it."""
    roots: dict[str, set[str]] = {}
    for path in sorted(TESTS_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                modules = [node.module.split(".")[0]]
            else:
                continue
            for module in modules:
                roots.setdefault(module, set()).add(path.relative_to(REPO_ROOT).as_posix())
    return roots


def third_party_imports() -> dict[str, set[str]]:
    """The import roots under ``tests/`` that must come from a declared distribution."""
    return {
        module: files
        for module, files in _imported_roots().items()
        if module not in sys.stdlib_module_names and not _is_first_party(module)
    }


def undeclared_imports(declared: set[str]) -> dict[str, set[str]]:
    """Third-party imports under ``tests/`` that ``declared`` does not cover."""
    module_to_distributions = packages_distributions()
    offenders: dict[str, set[str]] = {}
    for module, files in third_party_imports().items():
        distributions = {_normalise(name) for name in module_to_distributions.get(module, [])}
        if not distributions or not (distributions & declared):
            offenders[module] = files
    return offenders


def test_every_third_party_test_import_is_declared() -> None:
    """A test may not import a distribution the project never asked for."""
    offenders = undeclared_imports(declared_distributions())

    assert not offenders, (
        "tests import distributions that pyproject does not declare in [dev]: "
        f"{ {module: sorted(files) for module, files in offenders.items()} }. "
        "Declare them, or drop the import (issue #526)."
    )


def test_pyyaml_is_declared_for_the_dev_extra() -> None:
    """The original defect: the Hard Rule 15 gate parses workflows with ``yaml``.

    Named explicitly so the reason outlives the general check above. ``pyyaml`` sits in
    ``[etl]`` for ``migration/``; it also has to be in ``[dev]`` because CI's
    ``pip install -e ".[dev]"`` is what the ``test`` job runs on.
    """
    assert "pyyaml" in declared_distributions()


def test_the_scan_actually_examined_third_party_imports() -> None:
    """Guard the guard: if the scan finds nothing, its silence means nothing."""
    examined = third_party_imports()

    assert len(examined) >= 5, f"only {len(examined)} third-party import roots found: {examined}"


def test_the_gate_can_fail() -> None:
    """Remove ``pyyaml`` from the declared set and ``yaml`` must be reported.

    Proves the check is wired to the declaration rather than to the installed environment —
    the exact confusion that let the original defect pass for as long as it did.
    """
    offenders = undeclared_imports(declared_distributions() - {"pyyaml"})

    assert "yaml" in offenders
    assert "tests/test_security_scanning.py" in offenders["yaml"]
