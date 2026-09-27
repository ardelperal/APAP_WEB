"""Guardian (issue #1019): every route in app/modules/** declares a guard decision.

JD-B-002 (judgment-day of #923): ``require_authorized_user`` validates the
session but never the ``rol`` VALUE — any authenticated session (unknown
rol string, ``reader``) reaches the handler. Issue #1019 promoted every
user-facing route that was guarded only by ``require_authorized_user`` to
an explicit decision (``require_permission`` from the RBAC matrix,
``require_writer_user`` for writes without a matrix permission, or a
documented allowlist exception).

This test statically scans every module under ``app/modules/`` with the
AST (same static-pin discipline as
``tests/test_auth_redirect_propagation_guardian.py``) and asserts that
each route handler declares one of the accepted rol-validating guards or
matches an explicit allowlist entry. The failure message names the exact
file, handler and (method, path) so the guard decision is forced per PR.

Accepted guards (all validate the rol value, fail-closed):
- ``require_permission`` — RBAC matrix (D-44 legacy mapping inside).
- ``require_writer_user`` — ``Settings.writer_rols`` (legacy writer set).
- ``require_developer_user`` / ``require_developer_user_redirect`` —
  developer-only guards (stricter than the writer set).
- Module-level aliases assigned from a ``require_permission(...)``
  call (repo pattern: ``_require_write_animales`` in animals/routes.py).

Known limitations (accepted, consistent with the existing pin tests):
- Detection is source-text based on AST names: a handler calling a
  helper that internally builds its own dependency would need a new
  allowlist entry — the failure message says so.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

_MODULES_DIR = Path(__file__).parents[1] / "app" / "modules"

#: Dependencies that validate the rol value (not just the session).
_ACCEPTED_ROL_GUARDS = frozenset({
    "require_permission",
    "require_writer_user",
    "require_developer_user",
    "require_developer_user_redirect",
})

#: Route handlers allowed to declare a guard outside _ACCEPTED_ROL_GUARDS.
#: Each entry pins the EXACT dependency the handler must declare, so a
#: silent downgrade to plain ``require_authorized_user`` also fails.
#: Every entry carries its justification — removing a route or changing
#: its guard requires updating this table in the same PR (issue #1019).
@dataclass(frozen=True)
class _AllowlistedRoute:
    module: str  # path relative to app/modules/
    handler: str
    method: str
    expected_dep: str
    justification: str


_ALLOWLIST: tuple[_AllowlistedRoute, ...] = (
    _AllowlistedRoute(
        module="tasks/routes.py",
        handler="listar_tareas",
        method="GET",
        expected_dep="require_known_rol",
        justification=(
            "issue #1019: the RBAC matrix has no read:tareas permission and "
            "this slice must not invent new permissions; the read keeps "
            "require_authorized_user composed with the module-local "
            "require_known_rol dep (fail-closed on unknown rol strings, "
            "same contract as D-44)"
        ),
    ),
    _AllowlistedRoute(
        module="tasks/routes.py",
        handler="detalle_tarea",
        method="GET",
        expected_dep="require_known_rol",
        justification=(
            "issue #1019: same tareas-read exception as listar_tareas — "
            "require_known_rol fail-closed rol-value validation"
        ),
    ),
)


@dataclass(frozen=True)
class _RouteFinding:
    module: str
    handler: str
    method: str
    path: str
    deps: frozenset[str]


def _permission_alias_names(tree: ast.Module) -> frozenset[str]:
    """Module-level names assigned from a ``require_permission(...)`` call."""
    aliases: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        value = node.value
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "require_permission"
        ):
            aliases.update(
                t.id for t in node.targets if isinstance(t, ast.Name)
            )
    return frozenset(aliases)


def _depends_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Collect the ``Depends(<name>)`` targets of a handler's parameters.

    Resolves both bare callables (``Depends(require_authorized_user)``)
    and parametrised deps (``Depends(require_permission(Permission.X))``),
    extracting the callee name in each case.
    """
    names: set[str] = set()
    args = list(node.args.args) + list(node.args.kwonlyargs)
    for arg in args:
        if arg.annotation is None:
            continue
        for sub in ast.walk(arg.annotation):
            if not (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Name)
                and sub.func.id == "Depends"
                and sub.args
            ):
                continue
            target = sub.args[0]
            if isinstance(target, ast.Name):
                names.add(target.id)
            elif isinstance(target, ast.Call) and isinstance(target.func, ast.Name):
                names.add(target.func.id)
    return names


def _route_findings(path: Path) -> list[_RouteFinding]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    findings: list[_RouteFinding] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not (
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and dec.func.attr in ("get", "post", "put", "patch", "delete")
            ):
                continue
            method = dec.func.attr.upper()
            route_path = ast.literal_eval(dec.args[0]) if dec.args else ""
            deps = frozenset(_depends_names(node))
            findings.append(
                _RouteFinding(
                    module=str(path.relative_to(_MODULES_DIR)),
                    handler=node.name,
                    method=method,
                    path=route_path,
                    deps=deps,
                )
            )
    return findings


def _classify(
    finding: _RouteFinding, aliases: frozenset[str]
) -> str | None:
    """Return None when the route has a guard decision, else a complaint."""
    if finding.deps & _ACCEPTED_ROL_GUARDS:
        return None
    if finding.deps & aliases:
        return None
    for entry in _ALLOWLIST:
        if (
            entry.module == finding.module
            and entry.handler == finding.handler
            and entry.method == finding.method
        ):
            if entry.expected_dep not in finding.deps:
                return (
                    f"allowlisted as '{entry.expected_dep}' but declares "
                    f"{sorted(finding.deps)} — justification: "
                    f"{entry.justification}"
                )
            if "require_authorized_user" in finding.deps:
                return (
                    f"allowlisted as '{entry.expected_dep}' but also declares "
                    f"require_authorized_user directly — the session-only "
                    f"guard must stay composed inside the allowlisted dep "
                    f"(justification: {entry.justification})"
                )
            return None
    return (
        f"no rol-validating guard decision (declares {sorted(finding.deps)}). "
        f"Fix: use require_permission(Permission.<X>) from the RBAC matrix, "
        f"require_writer_user for writes without a matrix permission, or add "
        f"a justified entry to _ALLOWLIST in "
        f"tests/test_rbac_route_guardian.py (issue #1019)."
    )


def _violations() -> list[str]:
    violations: list[str] = []
    for path in sorted(_MODULES_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        aliases = _permission_alias_names(tree)
        for finding in _route_findings(path):
            problem = _classify(finding, aliases)
            if problem is not None:
                violations.append(
                    f"{path}:{finding.handler} [{finding.method} "
                    f"{finding.path}] {problem}"
                )
    return violations


def test_every_route_declares_rol_validating_guard() -> None:
    """Guardian (issue #1019): routes must not rely on the session-only guard.

    Fails CI if a NEW route (or a regression in an existing one) declares
    only ``require_authorized_user`` — a guard that validates the session
    but never the rol value, reopening the JD-B-002 gap.
    """
    violations = _violations()
    assert not violations, (
        "Issue #1019 guardian: routes without a rol-validating guard "
        "decision found:\n\n" + "\n\n".join(violations)
    )
