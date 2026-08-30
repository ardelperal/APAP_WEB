"""Critical-helper and route-layer pytest coverage gates.

Enforces 100% line coverage on a named set of helpers plus every
``_row_to_*`` discovered in ``app/`` at runtime. Fails the pytest
session when any tracked helper drops below 100% line coverage; emits
a WARNING (not a fail) when the helper set is empty so a misconfigured
deploy does not block the build.

Spec: ``openspec/changes/hardening-2026-q2/specs/01-dev-tooling-gate/spec.md``
(REQ-3).
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

# --- CRITICAL_HELPERS contract -------------------------------------------

# Named entries per tasks.md:T-1B.4 and spec REQ-3. Adding a helper that
# does not match ``_row_to_*`` regex means adding one line here.
CRITICAL_HELPERS: frozenset[str] = frozenset(
    {
        "_redirect",
        "_render_form",
        "_is_duplicate_error",
        "optional_text",
        "optional_value",
        "required_text",
        "_resolve_developer_user",
        "_stamp_caller_fields",
        "_validate_secrets",
        "is_authenticated_user",
    }
)
# NOTE (issue #257 companion fix): ``_reverse_apply_one_row`` lives in
# ``migration/reverse_apply/per_row.py``, not ``app/``. This gate's
# ``coverage.json`` comes from CI's ``--cov=app`` run ([tool.coverage.run]
# source = ["app"] in pyproject.toml, per AGENTS.md rule 19) so a
# migration/-only function can NEVER appear in it — tracking it here was a
# permanent, structural 0% (not a real regression) that only became
# CI-blocking once the exit-code bug (#257) was fixed. Do not re-add it
# without also adding ``--cov=migration`` to CI, which is a separate,
# bigger decision (changes what the 80% floor measures).

_ROW_TO_PATTERN = re.compile(r"^_row_to_")
ROUTE_LAYER_MINIMUM = 85.0


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register ``--coverage-gate-config`` and ``--coverage-file``."""
    parser.addoption(
        "--coverage-gate-config",
        action="store",
        default=None,
        help="Path to TOML with [tool.apap.coverage_gate] (default: pyproject.toml).",
    )
    parser.addoption(
        "--coverage-file",
        action="store",
        default=None,
        help="Path to coverage.json (default: ./coverage.json).",
    )


# --- Coverage evaluation -------------------------------------------------


def evaluate_coverage(
    coverage_data: dict[str, Any],
    helpers: frozenset[str],
) -> tuple[bool, list[tuple[str, float]]]:
    """Return ``(passed, failures)`` where each failure is ``(name, pct)``.

    Empty ``helpers`` returns ``(True, [])`` — first-deploy safety per
    spec REQ-3 Scenario 2: misconfiguration must NOT block CI.
    A helper not in ``coverage.json`` counts as 0% and fails.
    """
    if not helpers:
        return True, []
    # ``coverage.json`` v1 schema: files[path].functions[name].summary.percent_covered.
    # Functions are keyed by bare name; collapse across files via max().
    seen: dict[str, float] = {}
    for file_data in coverage_data.get("files", {}).values():
        for func_name, func_data in file_data.get("functions", {}).items():
            if func_name not in helpers:
                continue
            pct = float(func_data.get("summary", {}).get("percent_covered", 0.0))
            seen[func_name] = max(seen.get(func_name, 0.0), pct)
    failures: list[tuple[str, float]] = [
        (h, seen.get(h, 0.0))
        for h in sorted(helpers)
        if seen.get(h, 0.0) < 100.0
    ]
    return (not failures), failures


def evaluate_route_coverage(
    coverage_data: dict[str, Any],
    minimum: float,
    expected_paths: frozenset[str] | None = None,
) -> tuple[bool, list[tuple[str, float]]]:
    """Enforce a line-coverage floor for every application route module."""
    route_files: dict[str, dict[str, Any]] = {}
    for raw_path, file_data in coverage_data.get("files", {}).items():
        path = str(raw_path).replace("\\", "/")
        filename = path.rsplit("/", 1)[-1]
        if path.startswith("app/modules/") and (
            filename == "routes.py" or filename.endswith("_routes.py")
        ):
            route_files[path] = file_data

    failures: list[tuple[str, float]] = []
    for path in sorted(expected_paths or frozenset(route_files)):
        file_data = route_files.get(path, {})
        summary = file_data.get("summary", {})
        statements = int(summary.get("num_statements", 0))
        covered = int(summary.get("covered_lines", 0))
        percentage = 0.0 if statements == 0 else covered * 100.0 / statements
        if percentage < minimum:
            failures.append((path, percentage))
    return (not failures), failures


# --- Helpers discovery ---------------------------------------------------


def discover_row_to_helpers(app_root: Path) -> frozenset[str]:
    """Return every function whose name matches ``_row_to_*`` under ``app_root``."""
    if not app_root.exists():
        return frozenset()
    out: set[str] = set()
    for py in app_root.rglob("*.py"):
        if "__pycache__" in py.parts or py.name == "__init__.py":
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                if _ROW_TO_PATTERN.match(node.name):
                    out.add(node.name)
    return frozenset(out)


def gather_helpers(
    app_root: Path, extra: frozenset[str]
) -> frozenset[str]:
    """Union of CRITICAL_HELPERS + regex-discovered + extras."""
    return CRITICAL_HELPERS | discover_row_to_helpers(app_root) | extra


def discover_route_files(app_root: Path) -> frozenset[str]:
    """Return normalized coverage.py paths for every route module."""
    modules_root = app_root / "modules"
    if not modules_root.exists():
        return frozenset()
    return frozenset(
        path.relative_to(app_root.parent).as_posix()
        for path in modules_root.rglob("*routes.py")
        if "__pycache__" not in path.parts
    )


def _load_config(config_path: Path | None) -> dict[str, Any]:
    """Load [tool.apap.coverage_gate] from a TOML file."""
    if config_path is None:
        config_path = Path.cwd() / "pyproject.toml"
    if not config_path.exists():
        return {}
    with config_path.open("rb") as fh:
        data = tomllib.load(fh)
    return data.get("tool", {}).get("apap", {}).get("coverage_gate", {})


# --- Pytest terminal summary hook ----------------------------------------


def _print_summary(
    passed: bool,
    failures: list[tuple[str, float]],
    helpers: frozenset[str],
    route_failures: list[tuple[str, float]],
    route_minimum: float,
    terminalreporter: Any,
) -> None:
    if not helpers:
        terminalreporter.write_sep(
            "=",
            "coverage-gate WARNING: CRITICAL_HELPERS empty; "
            "no-op (first-deploy safety per spec REQ-3 Scenario 2).",
            yellow=True,
        )
        return
    if passed:
        terminalreporter.write_sep(
            "=",
            (
                f"coverage-gate PASS: all {len(helpers)} helpers at 100% "
                f"and all route modules at least {route_minimum:.0f}%."
            ),
            green=True,
        )
        return
    lines = ["coverage-gate FAIL:"]
    if failures:
        lines.append(f"{len(failures)} helper(s) below 100%:")
        for name, pct in failures:
            lines.append(f"  - {name}: {pct:.1f}%")
    if route_failures:
        lines.append(
            f"{len(route_failures)} route module(s) below {route_minimum:.0f}%:"
        )
        for path, pct in route_failures:
            lines.append(f"  - {path}: {pct:.1f}%")
    terminalreporter.write_sep("=", "\n".join(lines), red=True)


def _evaluate_gate(
    config: pytest.Config,
) -> tuple[
    bool,
    list[tuple[str, float]],
    frozenset[str],
    list[tuple[str, float]],
    float,
] | None:
    """Load coverage.json + config and run ``evaluate_coverage``.

    Returns ``None`` when there is no ``coverage.json`` to evaluate (no
    ``--cov`` run; gate is a no-op), otherwise ``(passed, failures, helpers)``.
    """
    explicit_coverage_file = config.getoption("--coverage-file")
    coverage_requested = bool(
        config.getoption("cov_source", default=None)
    )
    if not coverage_requested and explicit_coverage_file is None:
        return None
    coverage_path = Path(explicit_coverage_file or "coverage.json")
    if not coverage_path.exists():
        return None
    cfg_opt = config.getoption("--coverage-gate-config")
    gate_cfg = _load_config(Path(cfg_opt) if cfg_opt else None)
    helpers = gather_helpers(
        app_root=Path.cwd() / "app",
        extra=frozenset(gate_cfg.get("extra_helpers", [])),
    )
    with coverage_path.open(encoding="utf-8") as fh:
        coverage_data = json.load(fh)
    helper_passed, failures = evaluate_coverage(coverage_data, helpers)
    route_minimum = float(
        gate_cfg.get("route_layer_minimum", ROUTE_LAYER_MINIMUM)
    )
    route_passed, route_failures = evaluate_route_coverage(
        coverage_data,
        route_minimum,
        expected_paths=discover_route_files(Path.cwd() / "app"),
    )
    return (
        helper_passed and route_passed,
        failures,
        helpers,
        route_failures,
        route_minimum,
    )


@pytest.hookimpl(tryfirst=True)
def pytest_terminal_summary(
    terminalreporter: Any,
    config: pytest.Config,
) -> None:
    """After pytest writes coverage.json, evaluate the gate and print the banner.

    Enforcement (failing the actual process) happens in
    ``pytest_sessionfinish`` below — ``config.exitstatus`` is a no-op here;
    ``_pytest.main.wrap_session`` only reads back ``session.exitstatus``
    (issue #257).
    """
    result = _evaluate_gate(config)
    if result is None:
        return
    passed, failures, helpers, route_failures, route_minimum = result
    _print_summary(
        passed,
        failures,
        helpers,
        route_failures,
        route_minimum,
        terminalreporter,
    )


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: pytest.Session) -> None:
    """Fail the pytest PROCESS when the coverage gate fails (issue #257).

    ``_pytest.main.wrap_session`` returns ``session.exitstatus`` as the
    final process exit code; it never reads ``config.exitstatus`` back.
    Mutating ``session.exitstatus`` here is the documented, effective way
    for a plugin to force a non-zero exit. Reuses the exact same
    ``evaluate_coverage``/``gather_helpers`` logic as the terminal-summary
    banner above (and the CLI ``main()``) — no duplicated gate logic.
    """
    result = _evaluate_gate(session.config)
    if result is None:
        return
    passed, _failures, _helpers, _route_failures, _route_minimum = result
    if not passed:
        session.exitstatus = 1


# --- CLI entry point for CI ----------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m scripts.pytest_plugin.coverage_gate",
        description=(
            "Parse coverage.json, verify CRITICAL_HELPERS at 100%, and "
            "enforce the configured route-layer line floor."
        ),
    )
    p.add_argument("--coverage-file", default="coverage.json")
    p.add_argument("--config", default=None)
    p.add_argument("--app-root", default="app")
    p.add_argument(
        "--helpers",
        action="append",
        default=None,
        help="Override tracked helpers (repeatable). Skips auto-discovery.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns 0 on pass, 1 on fail (raises SystemExit), 2 on bad input."""
    args = _build_parser().parse_args(argv)
    coverage_path = Path(args.coverage_file)
    if not coverage_path.exists():
        print(
            f"coverage-gate: {coverage_path} not found; run pytest --cov first",
            file=sys.stderr,
        )
        return 2
    gate_cfg = _load_config(Path(args.config) if args.config else None)
    helpers = (
        frozenset(args.helpers)
        if args.helpers
        else gather_helpers(
            app_root=Path(args.app_root),
            extra=frozenset(gate_cfg.get("extra_helpers", [])),
        )
    )
    with coverage_path.open(encoding="utf-8") as fh:
        coverage_data = json.load(fh)
    helper_passed, failures = evaluate_coverage(coverage_data, helpers)
    route_minimum = float(
        gate_cfg.get("route_layer_minimum", ROUTE_LAYER_MINIMUM)
    )
    route_passed, route_failures = evaluate_route_coverage(
        coverage_data,
        route_minimum,
        expected_paths=discover_route_files(Path(args.app_root)),
    )
    passed = helper_passed and route_passed
    if not helpers:
        print(
            "coverage-gate WARNING: no helpers tracked "
            "(first-deploy safety; gate is no-op)."
        )
        return 0
    if passed:
        names = ", ".join(sorted(helpers))
        print(f"coverage-gate PASS: {len(helpers)} helper(s) at 100% ({names}).")
        return 0
    print(
        f"coverage-gate FAIL: {len(failures)} helper(s) below 100%:",
        file=sys.stderr,
    )
    for name, pct in failures:
        print(f"  - {name}: {pct:.1f}%", file=sys.stderr)
    for path, pct in route_failures:
        print(
            f"  - {path}: {pct:.1f}% (route floor {route_minimum:.1f}%)",
            file=sys.stderr,
        )
    raise SystemExit(1)


if __name__ == "__main__":
    raise SystemExit(main())
