"""AST-based rule linter for APAP_WEB AGENTS.md rules (Slice 1 of hardening-2026-q2).

Detects four AGENTS.md:300-308 violations: Rule 1 (routes must not call
client.execute_sql), Rule 4 partial (DDL must not hardcode the role
list), Rule 6 (auth defaults must deny, not permit), Rule 7 (redirects
are RedirectResponse, not HTTPException). Stdlib ``ast``.

PR-1B of hardening-2026-q2 added ``--exclude`` / ``.check_rulesignore``
so the six known false positives in the infrastructure layer (the
linter's own self-reference, the positive fixtures, and the migration
sandbox DDL) can be silenced without disabling the gate.
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


# Constants: Rule 1 verbs (GET exempt), Rule 7 redirect codes, Rule 4 marker,
# APAP003 forbidden logger methods, excluded dirs.
_WRITE_HTTP_VERBS = frozenset({"post", "put", "patch", "delete"})
_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
_DDL_ROLE_CHECK_MARKER = "CHECK (rol IN ("
_APAP003_FORBIDDEN_LOG_METHODS = frozenset(
    {"info", "warning", "error", "debug", "critical", "exception"}
)
_EXCLUDED_PARTS = frozenset({"__pycache__", ".venv", "venv", ".git", "build", "dist"})

# Default exclusion set (PR-1B + PR-6B). Silences known false positives
# verified on staging after PR-1A/PR-6A merged (see
# openspec/changes/hardening-2026-q2/apply-progress-pr-1a.md
# "Known limitations / follow-ups" and apply-progress-pr-6a/b.md).
# Each entry is a repo-root-relative POSIX-style path prefix matched
# against ``Violation.file``.
DEFAULT_EXCLUDES: frozenset[str] = frozenset(
    {
        # Detector 4 hits its own marker at lines 29 + 245.
        "scripts/check_rules.py",
        # Positive fixtures: every detector1/3/4_positive fixture is
        # intentional violation seed material.
        "tests/_rule_helpers/fixtures",
        # Migration-004 sandbox recreates the pre-fix CHECK clause to
        # verify the migration drops it (Detector 4 fires on the seed DDL).
        "tests/test_migration_004.py",
        # PR-6A added app/core/logging.py — the ONLY legal caller of
        # ``logging.getLogger(...)`` (it owns the log_safe wrapper).
        # Detector 5 (APAP003) skips it via the same path prefix.
        "app/core/logging.py",
    }
)

_IGNORE_FILENAME = ".check_rulesignore"


def find_violations(
    repo_root: Path,
    exclude: frozenset[str] | None = None,
) -> list[Violation]:
    """Scan ``repo_root`` for violations across all four detectors.

    ``exclude`` is a set of repo-root-relative POSIX-style path prefixes
    (``"scripts/check_rules.py"``, ``"tests/_rule_helpers/fixtures"``).
    Any ``Violation.file`` that starts with one of these prefixes is
    filtered out. ``None`` means no exclusion (back-compat).
    """
    if not repo_root.exists():
        return []
    excludes = exclude or frozenset()
    violations: list[Violation] = []
    for path in _iter_python_files(repo_root):
        violations.extend(_scan_file(path, repo_root))
    if excludes:
        return [v for v in violations if not _is_excluded(v.file, repo_root, excludes)]
    return violations


def _is_excluded(file: Path, repo_root: Path, excludes: frozenset[str]) -> bool:
    """Return True iff ``file`` matches any prefix in ``excludes``."""
    try:
        rel = file.resolve().relative_to(repo_root.resolve())
    except ValueError:
        # File is outside repo_root (e.g. a path passed via an absolute
        # argument). Fall back to the absolute path comparison so the
        # caller can still exclude by full path if needed.
        rel_str = str(file).replace("\\", "/")
        return any(rel_str.startswith(p.replace("\\", "/")) for p in excludes)
    rel_str = str(rel).replace("\\", "/")
    return any(
        rel_str == p.replace("\\", "/") or rel_str.startswith(p.rstrip("/") + "/")
        for p in excludes
    )


def parse_check_rulesignore(path: Path) -> frozenset[str]:
    """Parse a ``.check_rulesignore`` file (one path per line).

    Empty / missing file → empty frozenset. Lines starting with ``#``
    and blank lines are ignored. Trailing whitespace is stripped and
    paths are normalised to forward-slash for cross-platform matching.
    """
    if not path.exists():
        return frozenset()
    out: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.add(line.replace("\\", "/"))
    return frozenset(out)


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
    out.extend(_check_apap003_raw_logger_call(path, tree, repo_root))
    if _is_app_path(path, repo_root):
        out.extend(_check_print_in_app(path, tree))
    if _is_app_main_or_session(path, repo_root):
        out.extend(_check_csrf_samesite_strict(path, tree))
    if _is_app_main(path, repo_root):
        out.extend(_check_csrf_middleware_registered(path, tree))
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


# Detector 5 (APAP003) ---------------------------------------------------


def _is_app_path(path: Path, repo_root: Path) -> bool:
    """True if ``path`` lives under the repo's ``app/`` directory."""
    try:
        relative = path.relative_to(repo_root)
    except ValueError:
        return False
    return bool(relative.parts) and relative.parts[0] == "app"


def _is_logging_wrapper_path(path: Path, repo_root: Path) -> bool:
    """True if ``path`` is the structured-logging wrapper module.

    The wrapper is the ONLY legal caller of ``logging.getLogger(...)``
    because it owns :func:`log_safe`. Excluded from APAP003.
    """
    try:
        relative = path.relative_to(repo_root)
    except ValueError:
        return False
    return relative.parts == ("app", "core", "logging.py")


def _is_logger_chain(node: ast.AST) -> bool:
    """Match ``logger.X(...)`` and ``logging.getLogger(...).X(...)``.

    Mirrors ``scripts.ruff_plugin.apap_rules._is_logger_chain`` so the
    two detectors stay in lock-step. A bare ``logging.getLogger(name)``
    retrieval is NOT a chain and is therefore allowed (round-2 fix SB-7).
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


def _check_apap003_raw_logger_call(
    path: Path, tree: ast.AST, repo_root: Path
) -> list[Violation]:
    """Detector 5 — APAP003.

    Flags any ``logger.{info,warning,error,debug,critical,exception}(...)``
    call in ``app/`` except ``app/core/logging.py``. Forces every
    application module through :func:`app.core.logging.log_safe` so the
    structured-logging contract (JSON to stdout + closed-list
    redaction) is the only path to stdout.

    Spec: ``openspec/changes/hardening-2026-q2/specs/06-structured-logging/spec.md``
    (REQ-5, REQ-2). Tasks: T-6.3 (Slice 6).
    Round-2 fix SB-7: bare ``logging.getLogger(...)`` retrievals are
    allowed; only the chained method call is banned.
    """
    if not _is_app_path(path, repo_root):
        return []
    if _is_logging_wrapper_path(path, repo_root):
        return []
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr not in _APAP003_FORBIDDEN_LOG_METHODS:
            continue
        if not _is_logger_chain(func.value):
            continue
        violations.append(
            Violation(
                file=path,
                line=node.lineno,
                rule_id="apap003_raw_logger_call",
                message=(
                    "Raw logger.* call in app/. Use log_safe(event, **fields) "
                    "from app.core.logging — APAP003 forbids direct logger.* "
                    "calls (the structured-logging wrapper is the only "
                    "allowed entry point)."
                ),
            )
        )
    return violations


# Detectors 6, 7, 8 (Rules 9, 10 — hardening-2026-q2 final) -------------------


def _is_app_main(path: Path, repo_root: Path) -> bool:
    """True if ``path`` is ``app/main.py`` (the FastAPI app factory)."""
    try:
        relative = path.relative_to(repo_root)
    except ValueError:
        return False
    return relative.parts == ("app", "main.py")


def _is_app_main_or_session(path: Path, repo_root: Path) -> bool:
    """True if ``path`` is ``app/main.py`` or ``app/core/session.py``.

    These two files are where session cookies are set with
    ``samesite=...``. Any session-cookie regression to ``Lax`` fails
    Detectors 7+8. The short-lived OAuth PKCE verifier cookie is the
    deliberate exception: OAuth callbacks are top-level cross-site GET
    navigations, so that cookie must be ``Lax`` rather than ``Strict``.
    """
    try:
        relative = path.relative_to(repo_root)
    except ValueError:
        return False
    return relative.parts in {
        ("app", "main.py"),
        ("app", "core", "session.py"),
    }


# Detector 6 -----------------------------------------------------------------


def _check_print_in_app(path: Path, tree: ast.AST) -> list[Violation]:
    """Detector 6 — Rule 9.

    ``print(...)`` in ``app/`` bypasses the structured-logging pipeline
    and the redaction filter. Banned by Rule 9.
    """
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Name) and node.func.id == "print"):
            continue
        violations.append(
            Violation(
                file=path,
                line=node.lineno,
                rule_id="print_in_app",
                message=(
                    "print() in app/ is banned by Rule 9. "
                    "Use log_safe() from app.core.logging instead."
                ),
            )
        )
    return violations


# Detector 7 -----------------------------------------------------------------


def _check_csrf_middleware_registered(
    path: Path, tree: ast.AST
) -> list[Violation]:
    """Detector 7 — Rule 10.

    ``app/main.py`` MUST register ``CsrfMiddleware`` in the middleware
    chain. Catches accidental removal of the gate.
    """
    src = path.read_text(encoding="utf-8")
    if "CsrfMiddleware" in src:
        return []
    return [
        Violation(
            file=path,
            line=1,
            rule_id="csrf_middleware_registered",
            message=(
                "app/main.py does not register CsrfMiddleware. "
                "Add 'app.add_middleware(CsrfMiddleware)' to create_app(). "
                "Rule 10: CSRF defense per default."
            ),
        )
    ]


# Detector 8 -----------------------------------------------------------------


def _check_csrf_samesite_strict(
    path: Path, tree: ast.AST
) -> list[Violation]:
    """Detector 8 — Rule 10.

    Session cookies must use ``SameSite=Strict``. ``Lax`` is a
    regression that weakens the CSRF defense-in-depth posture.

    The short-lived ``apap_pkce`` OAuth verifier cookie is intentionally
    excluded: Google/InsForge returns to ``/auth/callback`` through a
    top-level cross-site GET and browsers do not send ``Strict`` cookies
    on that navigation. ``Lax`` is the safe OAuth-compatible setting for
    that verifier cookie.
    """
    src = path.read_text(encoding="utf-8")
    # Match both quote styles and avoid matching the comment in
    # app/main.py that says "Lax is a regression" (heuristic: only flag
    # lines that are clearly setting the attribute).
    import re
    bad_lines: list[int] = []
    lines = src.splitlines()
    for lineno, line in enumerate(lines, start=1):
        # Catch the canonical pattern: samesite="lax" or samesite='lax'
        # inside a set_cookie / response.set_cookie / cookie_params call.
        if re.search(r"""samesite\s*=\s*['"]lax['"]""", line):
            context = "\n".join(lines[max(0, lineno - 12) : lineno])
            if '"apap_pkce"' in context or "'apap_pkce'" in context:
                continue
            bad_lines.append(lineno)
    if not bad_lines:
        return []
    return [
        Violation(
            file=path,
            line=bad_lines[0],
            rule_id="csrf_samesite_strict",
            message=(
                "Cookie samesite='lax' is a regression. Use samesite='strict' "
                "for session cookies (Rule 10)."
            ),
        )
    ]


# CLI -----------------------------------------------------------------------


def _parse_args(argv: list[str]) -> tuple[list[Path], frozenset[str]]:
    """Parse positional paths + repeatable ``--exclude PATH`` flag.

    Returns ``(paths, excludes)``. Back-compat: with no ``--exclude``,
    excludes is empty (use ``DEFAULT_EXCLUDES`` from ``.check_rulesignore``).
    """
    paths: list[Path] = []
    excludes: set[str] = set()
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--exclude":
            i += 1
            if i >= len(argv):
                print(
                    "error: --exclude requires a path argument",
                    file=sys.stderr,
                )
                sys.exit(2)
            excludes.add(argv[i].replace("\\", "/"))
        elif arg.startswith("--exclude="):
            excludes.add(arg.split("=", 1)[1].replace("\\", "/"))
        elif arg in ("-h", "--help"):
            _print_usage()
            sys.exit(0)
        else:
            paths.append(Path(arg))
        i += 1
    return paths, frozenset(excludes)


def _print_usage() -> None:
    print(
        "usage: python scripts/check_rules.py <path> [<path>...]\n"
        "                  [--exclude <path>]... [--exclude=<path>]...\n"
        "\n"
        "Options:\n"
        "  --exclude PATH   Path prefix to exclude from results (repeatable).\n"
        "                   Default: paths listed in .check_rulesignore\n"
        "                   (repo-root) when present, plus the built-in\n"
        "                   DEFAULT_EXCLUDES (silences the 6 known false\n"
        "                   positives from PR-1A post-merge verification).",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        _print_usage()
        return 2
    paths, cli_excludes = _parse_args(args)
    if not paths:
        _print_usage()
        return 2
    # Exclusion precedence: CLI > .check_rulesignore > DEFAULT_EXCLUDES.
    # If the user passes any --exclude explicitly, use ONLY those (they
    # have decided the set). Otherwise consult the ignore file, then the
    # built-in defaults.
    if cli_excludes:
        excludes: frozenset[str] = cli_excludes
    else:
        ignore_path = Path.cwd() / _IGNORE_FILENAME
        file_excludes = parse_check_rulesignore(ignore_path)
        excludes = file_excludes | DEFAULT_EXCLUDES
    all_violations: list[Violation] = []
    for arg in paths:
        all_violations.extend(find_violations(arg.resolve(), exclude=excludes))
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
