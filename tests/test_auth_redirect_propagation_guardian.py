"""Guardian: every auth-gated handler must propagate the denial Response.

Issue #1002 (JD-B-001, judgment-day of #917): ``require_authorized_user``,
``require_writer_user`` and ``require_permission`` return a
``RedirectResponse`` when the session is absent or the user was
deactivated. FastAPI does NOT short-circuit when a dependency returns a
``Response`` — the value reaches the handler as a parameter. A handler
that ignores it renders the page for a deactivated user (GET routes)
or silently executes the write (POST routes); the ``auth.denied`` audit
event fires but the authorization guarantee does not hold. The denial
only takes effect when the handler propagates it via
``return_early_if_response`` — or delegates to a helper that calls it
internally (repo-established pattern: ``render_edit_form``,
``render_detail``, and per-module helpers like ``_do_batch_view``).

This test statically scans every module under ``app/modules/`` with the
AST (same static-pin discipline as ``tests/test_rule_7_compliance.py``)
and asserts that each handler whose parameters receive an auth-gate
dependency references a propagation seam. The failure message names the
exact file and handler so the fix is actionable.

Known limitations (accepted, consistent with the existing pin tests):
- Detection is source-text based: a reference inside a comment or
  docstring would false-pass. APAP002-style AST call detection would
  close this gap.
- The propagation-helper allowlist is explicit. A NEW shared helper
  that propagates internally must be added to ``_BASE_PROPAGATION``
  (and the test failure will say so); a module-local helper or partial
  alias is discovered automatically from its module source.
"""

from __future__ import annotations

import ast
from pathlib import Path

#: Dependencies that may return a denial ``RedirectResponse`` instead of
#: an authenticated-user payload. Compose on ``require_authorized_user``.
_AUTH_GATE_DEPS = frozenset({
    "require_authorized_user",
    "require_writer_user",
    "require_developer_user",
    "require_developer_user_redirect",
    "require_permission",
})

#: Names that count as "propagates the denial response".
#:
#: - ``return_early_if_response`` — the canonical seam every handler
#:   must call (or a helper of its own that calls it).
#: - Shared core helpers that call it internally on the handler's
#:   behalf (issue #681 JSCPD extraction). A new shared helper that
#:   propagates must be registered here.
_BASE_PROPAGATION = frozenset({
    "return_early_if_response",
    "render_edit_form",
    "render_detail",
})

_MODULES_DIR = Path(__file__).parents[1] / "app" / "modules"


def _module_source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _module_level_propagation_names(tree: ast.Module, source: str) -> frozenset[str]:
    """Resolve module-local names that propagate the denial response.

    Transitive closure over module-level definitions: a function or a
    top-level assignment (``_edit_x_form = partial(render_edit_form, ...)``)
    counts as propagating when its source references an already
    propagating name. This keeps per-module delegation patterns (partial
    wrappers, local orchestrators) covered without hard-coding them.
    """
    props: set[str] = set(_BASE_PROPAGATION)
    candidates: list[tuple[str, str]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            candidates.append((node.name, ast.get_source_segment(source, node) or ""))
        elif isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            for name in targets:
                candidates.append(
                    (name, ast.get_source_segment(source, node.value) or "")
                )
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.value is not None:
                candidates.append(
                    (node.target.id, ast.get_source_segment(source, node.value) or "")
                )
    changed = True
    while changed:
        changed = False
        for name, source in candidates:
            if name in props:
                continue
            if any(prop in source for prop in props):
                props.add(name)
                changed = True
    return frozenset(props)


def _is_auth_gated_handler(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return True when a handler parameter receives an auth-gate dependency.

    Recognises both the legacy ``x = Depends(require_...)`` default and
    the modern ``Annotated[X, Depends(require_...)]`` annotation.
    """
    args = list(node.args.args) + list(node.args.kwonlyargs)
    defaults = [d for d in list(node.args.defaults) + list(node.args.kw_defaults) if d is not None]
    for arg in args:
        if arg.annotation and any(
            isinstance(n, ast.Name) and n.id in _AUTH_GATE_DEPS
            for n in ast.walk(arg.annotation)
        ):
            return True
    for default in defaults:
        if any(isinstance(n, ast.Name) and n.id in _AUTH_GATE_DEPS for n in ast.walk(default)):
            return True
    return False


def _find_violations() -> list[str]:
    """Scan every module under ``app/modules/`` and return actionable findings."""
    violations: list[str] = []
    for path in sorted(_MODULES_DIR.rglob("*.py")):
        source = _module_source(path)
        tree = ast.parse(source, filename=str(path))
        propagation = _module_level_propagation_names(tree, source)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not _is_auth_gated_handler(node):
                continue
            segment = ast.get_source_segment(source, node) or ""
            if any(prop in segment for prop in propagation):
                continue
            violations.append(
                f"{path}:{node.lineno} handler '{node.name}' receives an "
                f"auth-gate dependency but never references "
                f"return_early_if_response (or a known propagation "
                f"helper). A deactivated/anonymous user reaches the "
                f"handler body. Fix: add "
                f"'if (early := return_early_if_response(<user>)) is not None: "
                f"return early' at the top of the handler (issue #1002). "
                f"If propagation happens inside a NEW shared helper, "
                f"register it in _BASE_PROPAGATION of "
                f"tests/test_auth_redirect_propagation_guardian.py."
            )
    return violations


def test_every_auth_gated_handler_propagates_denial_response() -> None:
    """Guardian (issue #1002): auth-gated handlers MUST propagate the denial.

    Fails CI if a NEW handler (or a regression in an existing one)
    receives ``require_authorized_user`` / ``require_writer_user`` /
    ``require_permission`` and ignores the ``RedirectResponse`` denial.
    """
    violations = _find_violations()
    assert not violations, (
        "Issue #1002 guardian: handlers that ignore the auth-denial "
        "RedirectResponse found:\n\n" + "\n\n".join(violations)
    )
