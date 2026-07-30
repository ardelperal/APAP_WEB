"""Route-handler size ratchet for APAP_WEB (AGENTS.md rule 28, issue #233).

Companion to ``scripts/check_module_size.py`` (rule 21), scoped to
individual FastAPI route-handler *functions* instead of whole modules.
Rule 1 already says routes must be HTTP-only (parsing, auth guards,
redirects, rendering); this script makes that boundary automatable: a
route handler that keeps growing is usually a sign that domain policy
(validation, fail-closed decisions, business rules) leaked into the
route instead of living in the service layer.

Enforces a hard budget (``MAX_LINES``) for every function decorated
with ``@router.<verb>(...)`` (any module under ``app/`` whose filename
contains ``routes``) or ``@application.<verb>(...)`` (``app/main.py``).
Handlers that already exceeded the budget when the rule landed
(2026-07-20 architecture review, issue #233's ``animal_foto`` plus 14
siblings measured the same day) live in an explicit ``BASELINE`` dict
that is a **ratchet**: entries may only shrink or disappear, never
grow, and no new entry may ever be added — split the non-HTTP logic
into the service layer instead.

Usage::

    python scripts/check_route_size.py [root]

``root`` defaults to the repository root (the parent of ``scripts/``).
Exit code 0 when clean, 1 on any violation. Stdlib-only, deterministic.

Tests: ``tests/test_route_size.py``.
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Mapping
from pathlib import Path

#: Hard budget for any NEW route handler. Calibrated against the real
#: distribution measured on 2026-07-20: median handler is 22 lines,
#: mean ~32; the vast majority sit at 10-30 lines. 50 sits just above
#: the "everything below here is unremarkable" knee of that
#: distribution — the 15 handlers already over it are exactly the ones
#: the architecture review flagged as mixing HTTP glue with domain
#: logic.
MAX_LINES = 50

#: HTTP verbs recognized as route decorators (mirrors
#: ``scripts/check_rules.py``'s ``_decorator_http_verb``).
_HTTP_VERBS = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})

#: Names a route decorator's ``@<name>.<verb>(...)`` call is bound to:
#: ``router`` for ``APIRouter`` instances (every ``app/modules/*/routes*.py``),
#: ``application`` for the FastAPI app factory (``app/main.py``).
_ROUTER_NAMES = frozenset({"router", "application"})

#: Known offenders at the time rule 28 landed (2026-07-20 audit). Keys
#: are ``<POSIX path relative to repo root>::<function name>``; values
#: are the exact line spans (``end_lineno - lineno + 1``) recorded that
#: day. RATCHET: entries may only shrink or disappear. When you reduce
#: one of these handlers, update its entry to the new (smaller) span in
#: the same PR — tests/test_route_size.py::test_baseline_matches_measured_tree
#: fails on any drift between this dict and the real tree. Never add a
#: new entry: split the handler instead.
BASELINE: dict[str, int] = {
    "app/modules/foster/assignment_routes.py::asignar_submit": 111,
    "app/main.py::callback": 107,
    "app/modules/acogidas/routes.py::create_acogida_view": 103,
    "app/modules/materiales/acogida_routes.py::assign_material_to_estancia_view": 89,
    "app/modules/cesiones/routes.py::create_cesion_view": 87,
    "app/modules/adopciones/routes.py::create_adopcion_view": 86,
    "app/modules/acogidas/routes.py::update_acogida_view": 86,
    "app/modules/adopciones/routes.py::update_adopcion_view": 84,
    "app/modules/entradas/batch_routes.py::stage_batch_view": 77,
    "app/modules/sanidad/routes.py::update_actuacion_view": 72,
    "app/modules/sanidad/routes.py::create_actuacion_view": 67,
    "app/modules/materiales/routes.py::update_material_view": 60,
    "app/modules/materiales/routes.py::create_material_view": 57,
    "app/modules/animals/routes.py::create_animal_view": 54,
}


def _is_route_decorator(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _HTTP_VERBS
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in _ROUTER_NAMES
    )


def _iter_route_files(root: Path) -> list[Path]:
    """Every ``app/**/*routes*.py`` file plus ``app/main.py``.

    ``*routes*.py`` (not the narrower ``routes*.py``) is deliberate:
    ``batch_routes.py``, ``acogida_routes.py`` and
    ``assignment_routes.py`` all declare route handlers too.
    """
    app_dir = root / "app"
    if not app_dir.is_dir():
        return []
    files = {
        p for p in app_dir.rglob("*routes*.py") if "__pycache__" not in p.parts
    }
    main_py = app_dir / "main.py"
    if main_py.is_file():
        files.add(main_py)
    return sorted(files)


def _iter_route_handlers(path: Path) -> list[tuple[str, int]]:
    """Return ``(function_name, line_span)`` for every route handler
    defined in ``path``. Line span is ``end_lineno - lineno + 1`` over
    the ``def``/``async def`` node (decorator lines are not counted,
    matching ``check_module_size.py``'s plain-line-count spirit).
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return []
    handlers: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(_is_route_decorator(d) for d in node.decorator_list):
            continue
        end = node.end_lineno if node.end_lineno is not None else node.lineno
        handlers.append((node.name, end - node.lineno + 1))
    return handlers


def check_tree(
    root: Path,
    *,
    max_lines: int = MAX_LINES,
    baseline: Mapping[str, int] | None = None,
) -> tuple[list[str], list[str]]:
    """Check every route handler under ``root``'s ``app/`` tree.

    Returns ``(violations, notices)`` — same contract as
    ``check_module_size.check_tree``.
    """
    if baseline is None:
        baseline = BASELINE
    violations: list[str] = []
    notices: list[str] = []
    seen: set[str] = set()

    for path in _iter_route_files(root):
        rel = path.relative_to(root).as_posix()
        for name, lines in _iter_route_handlers(path):
            key = f"{rel}::{name}"
            if key in baseline:
                seen.add(key)
                budget = baseline[key]
                if lines > budget:
                    violations.append(
                        f"{key}: {lines} lines, grew beyond its baseline of "
                        f"{budget} (ratchet: baselined handlers may only "
                        f"shrink — extract the non-HTTP logic into the "
                        f"service layer instead of growing the handler)"
                    )
                elif lines < budget:
                    notices.append(
                        f"{key}: {lines} lines, below its baseline of "
                        f"{budget} — update BASELINE in "
                        f"scripts/check_route_size.py to lock in the "
                        f"improvement"
                        + (
                            f" (now within the {max_lines}-line budget: "
                            f"remove the entry entirely)"
                            if lines <= max_lines
                            else ""
                        )
                    )
            elif lines > max_lines:
                violations.append(
                    f"{key}: {lines} lines, exceeds the {max_lines}-line "
                    f"budget (AGENTS.md rule 28) — move HTTP-unrelated "
                    f"logic to the service layer; do NOT add it to BASELINE"
                )

    for key in sorted(set(baseline) - seen):
        violations.append(
            f"{key}: baselined at {baseline[key]} lines but the handler "
            f"does not exist under {root} — remove the stale BASELINE entry"
        )

    return violations, notices


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    root = Path(args[0]).resolve() if args else Path(__file__).resolve().parents[1]

    violations, notices = check_tree(root)

    for notice in notices:
        print(f"NOTE {notice}")
    for violation in violations:
        print(f"FAIL {violation}")

    if violations:
        print(
            f"check_route_size: {len(violations)} violation(s). "
            f"Budget: {MAX_LINES} lines per route handler (AGENTS.md rule 28)."
        )
        return 1
    print("check_route_size: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
