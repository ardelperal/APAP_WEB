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


# --- APAP003: raw logger.* calls (ACTIVE since PR-6B, Slice 6) -----------


# APAP003 has a single file exclusion: ``app/core/logging.py`` is the
# ONLY legal caller of ``logging.getLogger(...)`` because it owns the
# structured-logging wrapper (``log_safe``). Excluding the file from
# the rule mirrors the AST linter's default-excludes policy. Suffixes
# cover both Unix and Windows path separators.
_APAP003_EXCLUDED_PATH_SUFFIXES: tuple[str, ...] = (
    "app/core/logging.py",
    "app\\core\\logging.py",
)


class APAP003Visitor(ast.NodeVisitor):
    """AST visitor for APAP003 — bans raw ``logger.*`` calls in ``app/``.

    Active since PR-6B (Slice 6, T-6.3): wires the rule into
    ``check_tree`` so a future ``select = ["APAP003"]`` ruff run
    resolves against this visitor. The authoritative CI gate is
    Detector 5 in ``scripts/check_rules.py`` (see round-2 fix PA-2);
    this visitor stays in lock-step with Detector 5 via the shared
    helper ``_is_logger_call``.

    The ``app/core/logging.py`` exclusion is intentional: that module
    owns the structured-logging wrapper. Every other module in
    ``app/`` MUST go through ``log_safe``.

    Round-2 fix SB-7: APAP003 does NOT ban ``logging.getLogger(...)``
    calls that do NOT chain into ``.info/.warning/.error/.debug/
    .critical/.exception``. The retrieval alone is fine; only the
    chained emission is banned.
    """

    _FORBIDDEN_ATTRS = frozenset(
        {"info", "warning", "error", "debug", "critical", "exception"}
    )

    def __init__(self, file: Path) -> None:
        self.file = file
        self.violations: list[APAPViolation] = []
        self._excluded = any(
            str(file).endswith(suffix)
            for suffix in _APAP003_EXCLUDED_PATH_SUFFIXES
        )

    def visit_Call(self, node: ast.Call) -> None:
        if self._excluded:
            return
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr in self._FORBIDDEN_ATTRS
            and _is_logger_chain(func.value)
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


def _is_logger_chain(node: ast.AST) -> bool:
    """Match ``logger.X(...)`` and ``logging.getLogger(...).X(...)``.

    Shared between APAP003Visitor and the AST linter's Detector 5 so
    the two stay in lock-step. A bare ``logging.getLogger(__name__)``
    retrieval is NOT a logger call chain and is therefore allowed.
    """
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


# --- APAP004: Any annotation on auth dependency params ----------------------


_APAP004_AUTH_DEP_FUNCTIONS: frozenset[str] = frozenset(
    {
        "require_authorized_user",
        "require_writer_user",
        "require_developer_user",
        "require_developer_user_redirect",
    }
)


class APAP004Visitor(ast.NodeVisitor):
    """AST visitor for APAP004 — bans ``Any`` on auth dependency params.

    Any parameter annotated as ``Any`` whose default is
    ``Depends(...)`` from ``app.core.auth_dependencies`` defeats mypy's
    type narrowing at the security boundary. The fix is a properly
    typed ``AuthenticatedUser`` (TypedDict) with a TypeGuard so mypy
    understands the narrowing performed by ``return_early_if_response``.
    """

    def __init__(self, file: Path) -> None:
        self.file = file
        self.violations: list[APAPViolation] = []

    def _check_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        all_args = list(node.args.posonlyargs) + list(node.args.args) + list(node.args.kwonlyargs)
        defaults = node.args.defaults
        kw_defaults = node.args.kw_defaults

        for i, arg in enumerate(all_args):
            # Check annotation is ast.Name(id="Any")
            if not (
                isinstance(arg.annotation, ast.Name)
                and arg.annotation.id == "Any"
            ):
                continue
            # Find the default
            num_positional_defaults = len(defaults)
            positional_count = len(node.args.posonlyargs) + len(node.args.args)
            if i < num_positional_defaults:
                default = defaults[i]
            elif i < positional_count + len(kw_defaults):
                kw_index = i - num_positional_defaults
                default = kw_defaults[kw_index]
            else:
                continue
            if default is None:
                continue
            if not isinstance(default, ast.Call):
                continue
            if not isinstance(default.func, ast.Name):
                continue
            if default.func.id != "Depends":
                continue
            if not default.args:
                continue
            depends_arg = default.args[0]
            if not isinstance(depends_arg, ast.Name):
                continue
            if depends_arg.id not in _APAP004_AUTH_DEP_FUNCTIONS:
                continue
            self.violations.append(
                APAPViolation(
                    file=self.file,
                    line=arg.lineno,
                    rule_id="APAP004",
                    message=(
                        f"Parameter {arg.arg!r} is typed Any but defaults to "
                        f"Depends({depends_arg.id}). Use a properly typed "
                        "AuthenticatedUser instead — APAP004 forbids Any on "
                        "auth dependency parameters."
                    ),
                )
            )

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_function(node)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef


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
        _RuleMeta("APAP004", "apap-any-auth-dep", APAP004Visitor),
    ]


# --- Public entry point --------------------------------------------------


def check_tree(tree: ast.AST, file: Path) -> list[APAPViolation]:
    """Walk ``tree`` and return every APAP001 + APAP003 + APAP004 violation."""
    apap001 = APAP001Visitor(file)
    apap001.visit(tree)
    apap003 = APAP003Visitor(file)
    apap003.visit(tree)
    apap004 = APAP004Visitor(file)
    apap004.visit(tree)
    return apap001.violations + apap003.violations + apap004.violations
