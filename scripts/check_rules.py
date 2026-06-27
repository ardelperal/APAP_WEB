"""AST-based rule linter for APAP_WEB AGENTS.md rules (Slice 1 of hardening-2026-q2).

Detects four AGENTS.md:300-308 violations: Rule 1 (routes must not call
client.execute_sql), Rule 4 partial (DDL must not hardcode the role
list), Rule 6 (auth defaults must deny, not permit), Rule 7 (redirects
are RedirectResponse, not HTTPException). Stdlib ``ast``.
"""


from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Violation:
    file: Path
    line: int
    rule_id: str
    message: str


# Constants: Rule 1 verbs (GET exempt), Rule 7 redirect codes, Rule 4 marker, excluded dirs.
_WRITE_HTTP_VERBS = frozenset({"post", "put", "patch", "delete"})
_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
_DDL_ROLE_CHECK_MARKER = "CHECK (rol IN ("
_EXCLUDED_PARTS = frozenset({"__pycache__", ".venv", "venv", ".git", "build", "dist"})


def find_violations(repo_root: Path) -> list[Violation]:
    """Scan ``repo_root`` for violations across all four detectors."""
    if not repo_root.exists():
        return []
    violations: list[Violation] = []
    for path in _iter_python_files(repo_root):
        violations.extend(_scan_file(path, repo_root))
    return violations


def _iter_python_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root] if root.suffix == ".py" else []
    return sorted(p for p in root.rglob("*.py") if not (set(p.parts) & _EXCLUDED_PARTS))


def _scan_file(path: Path, repo_root: Path) -> list[Violation]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return []
    out: list[Violation] = []
    out.extend(_check_route_uses_execute_sql(path, tree))
    if _is_auth_path(path, repo_root):
        out.extend(_check_auth_defaults_true(path, tree))
    out.extend(_check_http_exception_redirect(path, tree))
    out.extend(_check_hardcoded_role_check_in_ddl(path, tree))
    return out


# Detector 1 -----------------------------------------------------------------


def _check_route_uses_execute_sql(path: Path, tree: ast.AST) -> list[Violation]:
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        verb = _route_http_verb(node)
        if verb is None or verb not in _WRITE_HTTP_VERBS:
            continue
        for sub in ast.walk(node):
            if not _is_client_execute_sql_call(sub):
                continue
            violations.append(
                Violation(
                    file=path,
                    line=sub.lineno,
                    rule_id="route_uses_execute_sql",
                    message=(
                        f"Route '{node.name}' (@router.{verb}) calls "
                        "client.execute_sql directly. Move SQL to the service."
                    ),
                )
            )
    return violations


def _is_client_execute_sql_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "execute_sql"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "client"
    )


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


# Detector 2 ---------------------------------------------------------------


def _is_auth_path(path: Path, repo_root: Path) -> bool:
    try:
        relative = path.relative_to(repo_root)
    except ValueError:
        return False
    parts = relative.parts
    return (
        len(parts) >= 2
        and parts[0] == "core"
        and parts[-1].startswith("auth")
        and parts[-1].endswith(".py")
    )


def _check_auth_defaults_true(path: Path, tree: ast.AST) -> list[Violation]:
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if not _is_payload_get_is_authorized_true(node):
            continue
        violations.append(
            Violation(
                file=path,
                line=node.lineno,
                rule_id="auth_defaults_true",
                message=(
                    "auth defaults is_authorized to True (default-permit). "
                    "Rule 6 requires default-deny: payload.get('is_authorized', False)."
                ),
            )
        )
    return violations


def _is_payload_get_is_authorized_true(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if not isinstance(node.func, ast.Attribute) or node.func.attr != "get":
        return False
    if len(node.args) < 2:
        return False
    key, default = node.args[0], node.args[1]
    return (
        isinstance(key, ast.Constant)
        and key.value == "is_authorized"
        and isinstance(default, ast.Constant)
        and default.value is True
    )


# Detector 3 ---------------------------------------------------------------


def _check_http_exception_redirect(path: Path, tree: ast.AST) -> list[Violation]:
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if not _name_refers_to_http_exception(node.func.id, tree):
            continue
        status = _extract_status_code_kwarg(node)
        if status is None or status not in _REDIRECT_STATUS_CODES:
            continue
        violations.append(
            Violation(
                file=path,
                line=node.lineno,
                rule_id="http_exception_redirect",
                message=f"HTTPException with redirect status ({status}) violates Rule 7. Use RedirectResponse(url, status_code={status}).",
            )
        )
    return violations


def _name_refers_to_http_exception(name: str, tree: ast.AST) -> bool:
    body = getattr(tree, "body", None)
    if not body:
        return False
    for node in body:
        if isinstance(node, ast.ImportFrom) and node.module == "fastapi":
            for alias in node.names:
                if alias.name != "HTTPException":
                    continue
                if (alias.asname or alias.name) == name:
                    return True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if not alias.name.startswith("fastapi"):
                    continue
                parts = alias.name.split(".", 1)
                if len(parts) != 2 or parts[1] != "HTTPException":
                    continue
                if (alias.asname or "fastapi") == name:
                    return True
    return False


def _extract_status_code_kwarg(call: ast.Call) -> int | None:
    for kw in call.keywords:
        if kw.arg != "status_code":
            continue
        if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, int):
            return kw.value.value
    return None


# Detector 4 ---------------------------------------------------------------


def _check_hardcoded_role_check_in_ddl(path: Path, tree: ast.AST) -> list[Violation]:
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if _DDL_ROLE_CHECK_MARKER not in node.value:
            continue
        violations.append(
            Violation(
                file=path,
                line=node.lineno,
                rule_id="hardcoded_role_check_in_ddl",
                message=(
                    "DDL hardcodes role list with 'CHECK (rol IN (...)'. "
                    "Rule 4: derive from the Rol enum (single source of truth)."
                ),
            )
        )
    return violations


# CLI -----------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(
            "usage: python scripts/check_rules.py <path> [<path>...]",
            file=sys.stderr,
        )
        return 2
    all_violations: list[Violation] = []
    for arg in args:
        all_violations.extend(find_violations(Path(arg).resolve()))
    if all_violations:
        for v in sorted(all_violations, key=lambda x: (str(x.file), x.line)):
            print(f"{v.file}:{v.line}: {v.rule_id}: {v.message}")
        print(
            f"\n{len(all_violations)} violation(s) across "
            f"{len({str(v.file) for v in all_violations})} file(s).",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
