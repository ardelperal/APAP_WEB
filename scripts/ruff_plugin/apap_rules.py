"""Ruff APAP custom rules (PR-1B of hardening-2026-q2).

Implements two custom AST-based rules for APAP_WEB's domain:

- ``APAP001``: routes (``@router.{post,put,patch,delete}`` or
  ``@application.{...}``) MUST NOT call ``client.execute_sql`` directly —
  Rule 1 of ``AGENTS.md``. Mirrors ``scripts/check_rules.py`` Detector 1
  so the lint gate is also enforced when ruff runs in CI.
- ``APAP003``: bans raw ``logger.{info,warning,error,debug,critical,exception}(...)``
  calls in ``app/**`` (exposes ``log_safe`` as the only allowed logging
  entry). REGISTERED here (per ``tasks.md:T-1B.2``) so Slice 6 can flip
  it on in ``select`` without rewriting the rule; in this slice it is
  NOT wired into ``check_tree`` because the Slice 4 → Slice 5 transition
  window uses ``logging.getLogger(__name__).warning(...)`` as a
  placeholder (see design.md Slice 1, line 145-156).

Spec: ``openspec/changes/hardening-2026-q2/specs/01-dev-tooling-gate/spec.md``
(REQ-2).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

# Mirror scripts/check_rules.py constants (Detector 1) --------------------------

_WRITE_HTTP_VERBS = frozenset({"post", "put", "patch", "delete"})


@dataclass(frozen=True)
class APAPViolation:
    """A single rule violation. Mirrors scripts.check_rules.Violation."""

    file: Path
    line: int
    rule_id: str
    message: str


# --- AST helpers (mirror Detector 1) -------------------------------------


def _route_http_verb(func: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    for decorator in func.decorator_list:
        verb = _decorator_http_verb(decorator)
        if verb is not None:
            return verb
    return None


def _decorator_http_verb(node: ast.expr) -> str | None:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return None
    if node.func.attr not in {"get", "post", "put", "patch", "delete", "head", "options"}:
        return None
    if not isinstance(node.func.value, ast.Name):
        return None
    if node.func.value.id not in {"router", "application"}:
        return None
    return node.func.attr


def _is_client_execute_sql_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "execute_sql"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "client"
    )


# --- APAP001: route uses execute_sql (ACTIVE) ----------------------------


class APAP001Visitor(ast.NodeVisitor):
    """Mirror of ``scripts/check_rules.py`` Detector 1 in ruff's AST visitor.

    Fires on ``client.execute_sql(...)`` calls inside any function
    decorated with a write-verb ``@router.<verb>`` or
    ``@application.<verb>``. GET handlers are exempt per design.
    """

    def __init__(self, file: Path) -> None:
        self.file = file
        self.violations: list[APAPViolation] = []
        self._verb_stack: list[str | None] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        verb = _route_http_verb(node)
        # Only enforce inside write-verb handlers; allow reading other
        # functions (services, helpers) to call execute_sql freely.
        if verb in _WRITE_HTTP_VERBS:
            self._verb_stack.append(verb)
            self.generic_visit(node)
            self._verb_stack.pop()
        else:
            self._verb_stack.append(None)
            self.generic_visit(node)
            self._verb_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> None:
        if (
            self._verb_stack
            and self._verb_stack[-1] is not None
            and _is_client_execute_sql_call(node)
        ):
            verb = self._verb_stack[-1]
            self.violations.append(
                APAPViolation(
                    file=self.file,
                    line=node.lineno,
                    rule_id="APAP001",
                    message=(
                        f"Route handler (@{verb}) calls client.execute_sql "
                        "directly. Move SQL to the service layer (Rule 1)."
                    ),
                )
            )
        self.generic_visit(node)


# --- APAP003: raw logger.* calls (REGISTERED but NOT active) -------------


class APAP003Visitor(ast.NodeVisitor):
    """AST visitor for APAP003 — bans raw ``logger.*`` calls.

    DEFINED here per ``tasks.md:T-1B.2`` so Slice 6 can flip it on by
    adding ``APAP003`` to ``[tool.ruff.lint] select`` (T-6.4) and wiring
    the visitor into ``check_tree`` (T-6.3). NOT active in PR-1B to keep
    CI green during the Slice 4 → Slice 5 transition window where the
    CSRF middleware logs via ``logging.getLogger(__name__).warning(...)``
    as a placeholder (see ``design.md`` Slice 1, lines 145-156).
    """

    _FORBIDDEN_ATTRS = frozenset(
        {"info", "warning", "error", "debug", "critical", "exception"}
    )

    def __init__(self, file: Path) -> None:
        self.file = file
        self.violations: list[APAPViolation] = []

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr in self._FORBIDDEN_ATTRS
            and self._is_logger_chain(func.value)
        ):
            self.violations.append(
                APAPViolation(
                    file=self.file,
                    line=node.lineno,
                    rule_id="APAP003",
                    message=(
                        "Raw logger.* call in app/. Use log_safe(event, "
                        "**fields) from app.core.logging (Rule: structured "
                        "logging only)."
                    ),
                )
            )
        self.generic_visit(node)

    @staticmethod
    def _is_logger_chain(node: ast.AST) -> bool:
        """Match ``logger.X(...)`` and ``logging.getLogger(...).X(...)``."""
        if isinstance(node, ast.Name) and node.id == "logger":
            return True
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "getLogger"
        ):
            return True
        return False


# --- Plugin registry (for ruff 0.15+ entry-point discovery) --------------


class _RuleMeta:
    """Minimal ruff-rule metadata for plugin discovery."""

    def __init__(self, code: str, name: str, visitor_cls: type[ast.NodeVisitor]) -> None:
        self.code = code
        self.name = name
        self.visitor_cls = visitor_cls


def discover_rule_classes() -> list[_RuleMeta]:
    """Return the metadata for every rule this plugin registers.

    Used by ruff when loading the plugin via the ``[tool.ruff.lint]``
    extended-select mechanism and by tests to assert both APAP001
    (active) and APAP003 (registered, deferred to Slice 6) are present.
    """
    return [
        _RuleMeta("APAP001", "apap-route-uses-execute-sql", APAP001Visitor),
        _RuleMeta("APAP003", "apap-raw-logger-call", APAP003Visitor),
    ]


# --- Public entry point --------------------------------------------------


def check_tree(tree: ast.AST, file: Path) -> list[APAPViolation]:
    """Walk ``tree`` and return every APAP001 violation.

    APAP003 is intentionally NOT fired here: the rule's class is
    registered (``discover_rule_classes`` returns it) so Slice 6 can
    enable it by adding ``APAP003`` to ``select`` AND wiring the visitor
    into this function. Per ``design.md`` Slice 1, line 145-156, the
    transition window uses ``logging.getLogger(__name__).warning(...)``
    as a placeholder that must not trigger APAP003.
    """
    visitor = APAP001Visitor(file)
    visitor.visit(tree)
    return visitor.violations
