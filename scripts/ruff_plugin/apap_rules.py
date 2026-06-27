"""Ruff APAP custom rules (PR-1B of hardening-2026-q2).

Implements two custom AST-based rules for APAP_WEB's domain:

- ``APAP001``: routes (``@router.{post,put,patch,delete}`` or
  ``@application.{...}``) MUST NOT call ``client.execute_sql`` directly —
  Rule 1 of ``AGENTS.md``. Mirrors ``scripts/check_rules.py`` Detector 1
  so the lint gate is also enforceable from this module.
- ``APAP003``: bans raw ``logger.{info,warning,error,debug,critical,exception}(...)``
  calls in ``app/**`` (exposes ``log_safe`` as the only allowed logging
  entry). REGISTERED here per ``tasks.md:T-1B.2`` so Slice 6 can flip
  it on in ``select`` without rewriting the rule. NOT fired from
  ``check_tree`` because the Slice 4 → Slice 5 transition uses
  ``logging.getLogger(__name__).warning(...)`` as a placeholder.

Spec: ``openspec/changes/hardening-2026-q2/specs/01-dev-tooling-gate/spec.md``
(REQ-2).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

# Reuse the AST helpers from scripts/check_rules.py to avoid drift
# between the AST linter (Detector 1) and the ruff plugin (APAP001).
from scripts.check_rules import (  # noqa: F401 — re-exported indirectly
    _is_client_execute_sql_call,
    _route_http_verb,
)

_WRITE_HTTP_VERBS = frozenset({"post", "put", "patch", "delete"})


@dataclass(frozen=True)
class APAPViolation:
    """A single rule violation. Mirrors scripts.check_rules.Violation."""

    file: Path
    line: int
    rule_id: str
    message: str


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
        self._verb_stack.append(verb if verb in _WRITE_HTTP_VERBS else None)
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
    adding ``APAP003`` to ``[tool.ruff.lint] select`` (T-6.4). NOT
    active in PR-1B to keep CI green during the Slice 4 → Slice 5
    transition (see ``design.md`` Slice 1, lines 145-156).
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
                        "**fields) from app.core.logging."
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


# --- Plugin registry -----------------------------------------------------


class _RuleMeta:
    """Minimal ruff-rule metadata for plugin discovery."""

    def __init__(
        self, code: str, name: str, visitor_cls: type[ast.NodeVisitor]
    ) -> None:
        self.code = code
        self.name = name
        self.visitor_cls = visitor_cls


def discover_rule_classes() -> list[_RuleMeta]:
    """Return metadata for every rule this plugin registers."""
    return [
        _RuleMeta("APAP001", "apap-route-uses-execute-sql", APAP001Visitor),
        _RuleMeta("APAP003", "apap-raw-logger-call", APAP003Visitor),
    ]


# --- Public entry point --------------------------------------------------


def check_tree(tree: ast.AST, file: Path) -> list[APAPViolation]:
    """Walk ``tree`` and return every APAP001 violation.

    APAP003 is intentionally NOT fired here — see module docstring.
    """
    visitor = APAP001Visitor(file)
    visitor.visit(tree)
    return visitor.violations
