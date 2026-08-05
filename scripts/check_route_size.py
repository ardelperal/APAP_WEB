"""Route-handler size and Form-parameter ratchet for APAP_WEB (AGENTS.md rule 28, issue #233/337).

Companion to ``scripts/check_module_size.py`` (rule 21), scoped to
individual FastAPI route-handler *functions* instead of whole modules.
Rule 1 already says routes must be HTTP-only (parsing, auth guards,
redirects, rendering); this script makes that boundary automatable: a
route handler that keeps growing is usually a sign that domain policy
(validation, fail-closed decisions, business rules) leaked into the
route instead of living in the service layer.

**Line budget** (``MAX_LINES``): enforces a hard budget for every function
decorated with ``@router.<verb>(...)`` (any module under ``app/`` whose
filename contains ``routes``) or ``@application.<verb>(...)``
(``app/main.py``). Handlers that already exceeded the budget when the
rule landed live in an explicit ``BASELINE`` dict that is a
**ratchet**: entries may only shrink or disappear, never grow, and no
new entry may ever be added — split the non-HTTP logic into the service
layer instead.

**Form-parameter budget** (``MAX_FORM_PARAMS``): issue #337 found that
route handlers enumerated up to 26 individual ``Form(...)`` parameters,
making signatures unmaintainable. A 26-parameter handler cannot be read
safely, and every new field touches the handler, template and service in
three places. The fix is to bind forms to Pydantic models via
``Annotated[MyForm, Form()]`` instead of enumerating fields in the
signature.

The Form budget enforces a hard ceiling of ``MAX_FORM_PARAMS`` (8) per
handler. Handlers that already exceed this when the rule landed (measured
at commit ``adb83c5``) are tracked in ``FORM_BASELINE`` and may only
shrink — a handler that stays at 13 Form params after migration is
refactoring is still a violation; it must actually reduce the parameter
count to come off the baseline.

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

#: Hard budget for Form(...) parameters per route handler (issue #337).
#: A handler with more than 8 Form params is considered too wide to
#: read safely; the fix is to bind a Pydantic model via
#: ``Annotated[MyForm, Form()]`` instead of enumerating fields.
#: The 5 handlers already exceeding this when the rule landed are
#: tracked in FORM_BASELINE and must shrink when migrated.
MAX_FORM_PARAMS = 8

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
    # app/main.py::callback was extracted to app/core/auth_flow.py (#336).
    "app/modules/foster/assignment_routes.py::asignar_submit": 109,
    # issue #388: AcogidaForm migration shrank from 101 → 90; rebased on
    # origin/main, override_id moved into the form model, now 89.
    "app/modules/acogidas/routes.py::create_acogida_view": 89,
    "app/modules/materiales/acogida_routes.py::assign_material_to_estancia_view": 87,
    # issue #388: CesionForm migration shrank from 87 → 67 lines; still >50 budget
    "app/modules/cesiones/routes.py::create_cesion_view": 67,
    # issue #388: AcogidaForm migration shrank from 84 → 73 lines; still >50 budget
    "app/modules/acogidas/routes.py::update_acogida_view": 73,
    "app/modules/entradas/batch_routes.py::stage_batch_view": 77,
    # issue #388: ActuacionForm migration shrank from 70 → 64 lines; still >50 budget
    "app/modules/sanidad/routes.py::update_actuacion_view": 64,
    # issue #388: ActuacionForm migration shrank from 65 → 59 lines; still >50 budget
    "app/modules/sanidad/routes.py::create_actuacion_view": 59,
    # issue #388: MaterialForm migration shrank update_material_view 58 → 48 and
    # create_material_view 55 → 45 — both now within 50-line budget, removed from BASELINE
    "app/modules/animals/routes.py::create_animal_view": 54,
    # issue #337: AdopcionForm migration shrank these from 82/78 (RBAC-era) → 59/53
    # (still >50 budget; ratchet prevents growth — must shrink further)
    "app/modules/adopciones/routes.py::create_adopcion_view": 59,
    "app/modules/adopciones/routes.py::update_adopcion_view": 53,
}

#: Handlers that exceed MAX_FORM_PARAMS (8) when issue #337 was opened
#: (measured at commit ``adb83c5``). Values are the exact Form param
#: counts recorded that day. RATCHET: entries may only shrink or
#: disappear. When a migration actually reduces the param count, update
#: the entry to the new (lower) value — the notice will tell you to
#: remove it once it reaches 0 or falls below MAX_FORM_PARAMS. Never
#: add a new entry here: use a Pydantic model to consolidate params
#: instead.
# issue #388: CesionForm migration reduced Form params 21 → 0 (now uses
# Annotated[CesionForm, Form()] — single Pydantic model, no individual Form() params)
# All three handlers now have 0 or 1 Form params (≤ MAX_FORM_PARAMS=8) — REMOVED
FORM_BASELINE: dict[str, int] = {}


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
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if not any(_is_route_decorator(d) for d in node.decorator_list):
            continue
        end = node.end_lineno if node.end_lineno is not None else node.lineno
        handlers.append((node.name, end - node.lineno + 1))
    return handlers


def _count_form_params(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Count ``Form(...)`` references in a function's signature.

    Every FastAPI idiom the project uses is recognised:

    * ``x: Form() = ...`` — annotation IS the ``Form(...)`` call.
    * ``x: Annotated[T, Form()] = ...`` — ``Form(...)`` lives inside the
      annotation tree.
    * ``x = Form(...)`` — bare ``Form(...)`` default with no annotation.

    ``Form(...)`` calls inside the body are excluded (they would be
    legitimate uses of the Form class for dependency injection, not
    route-level form parameters).
    """
    count = 0
    for arg in node.args.args:
        if _annotation_uses_form(arg.annotation):
            count += 1
    for default in node.args.defaults or []:
        if _default_is_form(default):
            count += 1
    return count


def _annotation_uses_form(annotation: ast.expr | None) -> bool:
    """Return True when the annotation tree contains a ``Form(...)`` call."""
    if annotation is None:
        return False
    if isinstance(annotation, ast.Call):
        return (
            isinstance(annotation.func, ast.Name)
            and annotation.func.id == "Form"
        )
    if isinstance(annotation, ast.Subscript):
        return _annotation_uses_form(annotation.slice)
    if isinstance(annotation, ast.Tuple):
        return any(_annotation_uses_form(elt) for elt in annotation.elts)
    return False


def _default_is_form(default: ast.expr) -> bool:
    """Return True when the default expression is a bare ``Form(...)`` call."""
    if isinstance(default, ast.Call):
        return (
            isinstance(default.func, ast.Name)
            and default.func.id == "Form"
        )
    return False


def _iter_route_handlers_with_form_params(
    path: Path,
) -> list[tuple[str, int, int]]:
    """Return ``(function_name, line_span, form_param_count)`` for every
    route handler in ``path``.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return []
    handlers: list[tuple[str, int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(_is_route_decorator(d) for d in node.decorator_list):
            continue
        end = node.end_lineno if node.end_lineno is not None else node.lineno
        line_span = end - node.lineno + 1
        form_count = _count_form_params(node)
        handlers.append((node.name, line_span, form_count))
    return handlers


def check_tree(
    root: Path,
    *,
    max_lines: int = MAX_LINES,
    baseline: Mapping[str, int] | None = None,
    max_form_params: int = MAX_FORM_PARAMS,
    form_baseline: Mapping[str, int] | None = None,
) -> tuple[list[str], list[str]]:
    """Check every route handler under ``root``'s ``app/`` tree.

    Returns ``(violations, notices)`` — same contract as
    ``check_module_size.check_tree``. Checks both line spans (against
    ``baseline``) and Form parameter counts (against ``form_baseline``).
    """
    if baseline is None:
        baseline = BASELINE
    if form_baseline is None:
        form_baseline = FORM_BASELINE

    violations: list[str] = []
    notices: list[str] = []
    seen: set[str] = set()
    seen_form: set[str] = set()

    for path in _iter_route_files(root):
        rel = path.relative_to(root).as_posix()
        for name, lines, form_count in _iter_route_handlers_with_form_params(path):
            key = f"{rel}::{name}"

            # --- line-span check (existing) --------------------------------
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

            # --- Form-parameter check (issue #337) ---------------------------
            if key in form_baseline:
                seen_form.add(key)
                form_budget = form_baseline[key]
                if form_count > form_budget:
                    violations.append(
                        f"{key}: {form_count} Form params, grew beyond its "
                        f"FORM_BASELINE of {form_budget} (ratchet: baselined "
                        f"handlers may only shrink — bind a Pydantic model via "
                        f"Annotated[MyForm, Form()] to consolidate params)"
                    )
                elif form_count < form_budget:
                    notices.append(
                        f"{key}: {form_count} Form params, below its "
                        f"FORM_BASELINE of {form_budget} — update FORM_BASELINE "
                        f"in scripts/check_route_size.py to lock in the "
                        f"improvement"
                        + (
                            f" (now within the {max_form_params}-param budget: "
                            f"remove the entry entirely)"
                            if form_count <= max_form_params
                            else ""
                        )
                    )
            elif form_count > max_form_params:
                violations.append(
                    f"{key}: {form_count} Form params, exceeds the "
                    f"{max_form_params}-param budget (issue #337) — "
                    f"bind a Pydantic model via Annotated[MyForm, Form()] "
                    f"instead of enumerating fields; do NOT add it to "
                    f"FORM_BASELINE"
                )

    for key in sorted(set(baseline) - seen):
        violations.append(
            f"{key}: baselined at {baseline[key]} lines but the handler "
            f"does not exist under {root} — remove the stale BASELINE entry"
        )

    for key in sorted(set(form_baseline) - seen_form):
        violations.append(
            f"{key}: baselined at {form_baseline[key]} Form params but "
            f"the handler does not exist under {root} — remove the stale "
            f"FORM_BASELINE entry"
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
            f"Line budget: {MAX_LINES}/handler (AGENTS.md rule 28). "
            f"Form-param budget: {MAX_FORM_PARAMS}/handler (issue #337)."
        )
        return 1
    print("check_route_size: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
