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
import re
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Violation:
    file: Path
    line: int
    rule_id: str
    message: str


@dataclass(frozen=True)
class QuerySeamBaselineNote:
    """An INFORMATIONAL note emitted when a module in
    ``BASELINE_NO_QUERIES_MODULES`` is scanned.

    Unlike ``Violation``, this is NOT a CRITICAL and does not block CI.
    The note exists so the operator knows which legacy modules are
    grandfathered and therefore how much migration work remains to bring
    the codebase fully into compliance with Rule §22.

    Detector scope: modules under ``app/modules/`` that are listed in
    ``BASELINE_NO_QUERIES_MODULES``. When a non-baselined module has
    ``_*_SQL`` constants in ``service.py`` without a ``queries.py``
    seam, a ``Violation`` is emitted instead of (or in addition to) this
    note.
    """

    module_name: str
    file: Path
    line: int
    rule_id: str = "query_seam_baseline_note"
    message: str = ""


@dataclass(frozen=True)
class PiiRouteGap:
    """A WARNING-level surface drift between app/ routes and the
    ``PII_ROUTES_PARAMETRIZE`` tuple in ``tests/test_public_paths.py``.

    Emitted (NOT as a Violation, because warnings do not block CI) by
    :func:`find_pii_route_gaps` when a PII-shaped route in ``app/``
    is NOT covered by any parametrize entry, or when a parametrize
    entry has no matching route in ``app/``.

    Detector scope (PR5): routes under the three PII prefixes the
    PR5 spec mandates (``/voluntarios``, ``/animales``, ``/entradas``).
    The other PII-shaped modules the spec mentions (``/acogidas``,
    ``/adopciones``, ``/actuaciones`` — actually mounted at
    ``/sanidad`` in this codebase) are out of scope for THIS
    detector because their canonical list routes are not yet in
    ``PII_ROUTES_PARAMETRIZE``; a follow-up PR will add them and
    extend the detector. The detector is intentionally permissive
    (prefix-match: a parametrize entry ``/voluntarios/abc-123``
    covers routes like ``/voluntarios/new``, ``/voluntarios/{id}``,
    ``/voluntarios/{id}/deactivate``) so the existing PR5 routes
    pass without flags.
    """

    route_path: str
    file: Path | None
    line: int
    rule_id: str = "pii_route_coverage"
    message: str = ""


# Constants: Rule 1 verbs (GET exempt), Rule 7 redirect codes, Rule 4 marker,
# APAP003 forbidden logger methods, excluded dirs.
_WRITE_HTTP_VERBS = frozenset({"post", "put", "patch", "delete"})
_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
_DDL_ROLE_CHECK_MARKER = "CHECK (rol IN ("
_APAP003_FORBIDDEN_LOG_METHODS = frozenset(
    {"info", "warning", "error", "debug", "critical", "exception"}
)
_EXCLUDED_PARTS = frozenset({"__pycache__", ".venv", "venv", ".git", "build", "dist"})

# PR5 detector: prefixes the spec mandates as PII-shaped routes the
# closed-list audit covers. Routes starting with one of these are
# checked against ``PII_ROUTES_PARAMETRIZE``.
#
# The detector scope (PR5) is intentionally bounded to the three
# prefixes the PR5 ``PII_ROUTES_PARAMETRIZE`` tuple covers:
# ``/voluntarios``, ``/animales``, ``/entradas``. The spec mentions
# additional prefixes (``/acogidas``, ``/adopciones``,
# ``/actuaciones`` — actually mounted at ``/sanidad`` in this
# codebase) as PII-shaped but their canonical list routes are NOT
# in ``PII_ROUTES_PARAMETRIZE``. A follow-up PR will add parametrize
# entries for those modules AND extend the detector scope. Until
# then, restricting to the 3 covered prefixes keeps the gate silent
# on existing routes.
_PII_PREFIXES: tuple[str, ...] = (
    "/voluntarios",
    "/animales",
    "/entradas",
)
# Parametrize placeholder conventions: the test file uses ``abc-123``
# in ``/voluntarios/abc-123`` etc. as the canonical literal that
# represents "any single path segment". The route decorators use
# ``{param_name}`` (FastAPI path-parameter syntax). The detector
# treats both as single-segment wildcards so a parametrize entry
# covers any route under the same prefix tree.

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
        # Detector 13 query seam fixtures — the fixture modules themselves
        # (compliant, legacy, empty, sibling, synthetic_violation) are
        # scanned by the dedicated fixture tests and must not be hit by
        # the live repo scan.
        "tests/fixtures/query_seam",
    }
)

# Detector 13 (Rule 22) ----------------------------------------------------
#
# ``query_seam_violation`` — flags CRITICAL when a non-baselined
# ``app/modules/<M>/`` has a ``_*_SQL`` constant in ``service.py`` but no
# ``queries.py`` seam. The seven legacy modules already without
# ``queries.py`` are grandfathered in ``BASELINE_NO_QUERIES_MODULES``;
# adding any of them to the baseline is the correct migration path.
#
# Rationale: §22 requires query construction to live in ``queries.py``.
# The detector fires on ``service.py`` because that is the module
# developers edit when adding a new SQL statement — it is the natural
# place to enforce the seam. ``queries.py`` existence is the proxy for
# "this module has been migrated to the §22 pattern".
#
# The detector does NOT flag:
#   - Baselined legacy modules (they are grandfathered, migration is
#     tracked separately in issue #290).
#   - Modules whose ``service.py`` has no ``_*_SQL`` constants.
#   - Files other than ``service.py`` (e.g. ``batch_service.py``).
#   - ``queries.py`` itself (it is the seam, not a violation).
#
# The Informational ``query_seam_baseline_note`` is emitted for
# baselined modules that have ``_*_SQL`` constants so operators know
# how much grandfathered legacy remains.

BASELINE_NO_QUERIES_MODULES: frozenset[str] = frozenset(
    {
        "voluntarios",
        "sanidad",
        "cesiones",
        "animals",
        "foster",
        "entradas",
        "adopciones",
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
    violations.extend(_check_duplicate_helper_definitions(repo_root))
    # Detector 15 (issue #329): integration test coverage — repo-level,
    # runs after all per-file scans so all queries.py have been seen.
    violations.extend(_check_integration_test_coverage(repo_root))
    if excludes:
        return [v for v in violations if not _is_excluded(v.file, repo_root, excludes)]
    return violations


# Detector 9 (PR5) ----------------------------------------------------------
#
# ``pii_route_coverage`` — informational drift detector for the PR5
# ``PII_ROUTES_PARAMETRIZE`` tuple in ``tests/test_public_paths.py``.
# Emits WARNING-level :class:`PiiRouteGap` records (NOT
# :class:`Violation`) so the gate does not block CI but surfaces
# drift for the next operator pass. The matching is permissive
# (parametrize regex is a prefix of route regex with single-segment
# wildcards for both conventions) so the existing PR5 routes pass
# without flags.
#
# Scope (PR5): routes whose full URL starts with one of the three
# PR5-mandated PII prefixes (``/voluntarios``, ``/animales``,
# ``/entradas``). The other PII-shaped modules the spec mentions
# (``/acogidas``, ``/adopciones``, ``/actuaciones``) are deliberately
# out of scope for THIS detector — their canonical list routes are
# not yet in ``PII_ROUTES_PARAMETRIZE``. A follow-up PR will add them
# (and re-verify the existing code paths).

_PII_ROUTES_PARAMETRIZE_PATH = Path("tests/test_public_paths.py")


def _read_pii_routes_parametrize(repo_root: Path) -> tuple[str, ...] | None:
    """Parse ``PII_ROUTES_PARAMETRIZE`` from
    ``tests/test_public_paths.py`` via AST.

    Returns the tuple of parametrize entries, or ``None`` if the
    symbol is missing / unparseable. The detector bails (returns
    empty gap list) in that case so a transient parsing failure
    does not flood the operator output.

    Handles both bare ``PII_ROUTES_PARAMETRIZE = (...)`` (ast.Assign)
    and annotated ``PII_ROUTES_PARAMETRIZE: tuple[str, ...] = (...)``
    (ast.AnnAssign) declarations — the test file uses the latter.
    """
    full = repo_root / _PII_ROUTES_PARAMETRIZE_PATH
    if not full.exists():
        return None
    try:
        tree = ast.parse(full.read_text(encoding="utf-8"), filename=str(full))
    except (SyntaxError, UnicodeDecodeError):
        return None
    for node in ast.walk(tree):
        targets: list[ast.expr]
        value: ast.expr | None
        if isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        elif isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        else:
            continue
        if not any(
            isinstance(t, ast.Name) and t.id == "PII_ROUTES_PARAMETRIZE"
            for t in targets
        ):
            continue
        if not isinstance(value, ast.Tuple):
            continue
        out: list[str] = []
        for elt in value.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                out.append(elt.value)
        return tuple(out)
    return None


def _parametrize_entry_to_regex(entry: str) -> re.Pattern[str]:
    """Convert a parametrize entry to a single-segment wildcard regex.

    The PR5 convention uses ``abc-123`` as the literal placeholder
    for "any single path segment" (mirrors the FastAPI single-segment
    parameter convention). The detector rewrites ONLY the canonical
    ``abc-123`` placeholder as ``[^/]+``; other path-segment literals
    (``voluntarios``, ``animales``, ``entradas``, ...) match verbatim.

    The regex matches in two shapes:

    - ``^P$`` (exact match: the route URL equals the entry).
    - ``^P(/.*)?$`` (prefix match: the route URL starts with the
      entry AND optionally has additional ``/``-separated segments).

    The prefix match covers the common case where a parametrize
    entry for the LIST route (``/voluntarios``) covers the detail
    / form / edit routes (``/voluntarios/{id}``,
    ``/voluntarios/{id}/edit``, etc.).
    """
    # Substitute the canonical ``abc-123`` placeholder with a
    # single-segment wildcard. Other literals match verbatim
    # because ``abc-123`` is the only canonical placeholder in
    # the PR5 convention; module names like ``voluntarios`` /
    # ``animales`` / ``entradas`` stay literal. ``abc-123`` itself
    # is alphanumeric + dash, so it has no regex metacharacters
    # to escape; other literals in the entries are similarly safe.
    body = entry.replace("abc-123", "[^/]+")
    return re.compile(f"^{body}(/.*)?$")


def _route_decorator_path(node: ast.expr) -> str | None:
    """Extract the path string from a ``@router.METHOD(path, ...)``
    decorator. Returns ``None`` for non-HTTP decorators.
    """
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if not isinstance(func, ast.Attribute):
        return None
    if func.attr not in {"get", "post", "put", "patch", "delete", "head", "options"}:
        return None
    if not isinstance(func.value, ast.Name):
        return None
    if func.value.id not in {"router", "application"}:
        return None
    if not node.args:
        return None
    first = node.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def _api_router_prefix(tree: ast.AST) -> str:
    """Return the ``prefix=`` kwarg of the module-level ``router =
    APIRouter(...)`` assignment, or ``""`` if there is no prefix.

    The detector uses the prefix to construct the full URL of each
    route decorator: ``router_prefix + decorator_path``. FastAPI
    mounts the router at the prefix in ``app/main.py``.
    """
    for node in getattr(tree, "body", []):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(t, ast.Name) and t.id == "router" for t in node.targets
        ):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        call = node.value
        func = call.func
        # Match ``APIRouter(...)`` — either ``APIRouter`` (imported
        # directly) or ``fastapi.APIRouter`` (qualified import).
        if isinstance(func, ast.Attribute) and func.attr == "APIRouter":
            pass
        elif isinstance(func, ast.Name) and func.id == "APIRouter":
            pass
        else:
            continue
        for kw in call.keywords:
            if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                if isinstance(kw.value.value, str):
                    return kw.value.value
        return ""
    return ""


def _iter_app_route_files(repo_root: Path) -> list[Path]:
    """Yield every Python file under ``app/`` for the route-coverage
    detector. Skips ``__pycache__`` and the same excluded parts as
    the rest of the script.
    """
    app_dir = repo_root / "app"
    if not app_dir.exists():
        return []
    return sorted(
        p for p in app_dir.rglob("*.py") if not (set(p.parts) & _EXCLUDED_PARTS)
    )


def _collect_actual_routes(repo_root: Path) -> list[tuple[str, Path, int]]:
    """Walk every ``app/**/*.py`` and return the list of
    ``(full_url, file, line)`` for every ``@router.METHOD(...)``
    decorator found.

    The full URL is the concatenation of the module-level
    ``APIRouter(prefix=...)`` and the decorator path. Routes whose
    decorator path starts with ``/`` (absolute path) are emitted
    verbatim (the APIRouter prefix is ignored, matching FastAPI's
    documented behavior).
    """
    routes: list[tuple[str, Path, int]] = []
    for path in _iter_app_route_files(repo_root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        prefix = _api_router_prefix(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for decorator in node.decorator_list:
                p = _route_decorator_path(decorator)
                if p is None:
                    continue
                if p.startswith("/"):
                    full = p
                else:
                    full = prefix + p
                routes.append((full, path, decorator.lineno))
    return routes


def find_pii_route_gaps(repo_root: Path) -> list[PiiRouteGap]:
    """Return the list of :class:`PiiRouteGap` warnings for the
    PR5 ``pii_route_coverage`` detector.

    Detection logic:

    1. For every UNIQUE route in ``app/`` whose full URL starts with
       one of the three PR5-mandated PII prefixes (``/voluntarios``,
       ``/animales``, ``/entradas``), check whether the URL is covered
       by any entry in :data:`tests/test_public_paths.py::PII_ROUTES_PARAMETRIZE`.
       The URL is unique because the same path can have multiple
       decorators (GET, POST, DELETE) at the same URL — only one
       coverage check is needed per unique path.
    2. Coverage: the parametrize entry (with literal ``abc-123``
       segments rewritten as single-segment wildcards) equals the
       route URL (with ``{X}`` rewritten as single-segment wildcards)
       OR the parametrize regex is a strict prefix of the route
       regex. The strict-prefix case covers the common shape where
       a parametrize entry for the LIST route (``/voluntarios``)
       also covers the detail / form / edit routes
       (``/voluntarios/{id}``, ``/voluntarios/new``, etc.).

    Gaps are emitted (with the originating route file + line) for
    any uncovered route. The detector deliberately does NOT block
    CI — gaps are informational and surface drift for the next
    operator pass.

    Returns an empty list when ``PII_ROUTES_PARAMETRIZE`` cannot be
    parsed (transient parsing failure) so a missing file does not
    fail the rule gate.
    """
    parametrize_entries = _read_pii_routes_parametrize(repo_root)
    if parametrize_entries is None:
        return []

    parametrize_regexes = [
        _parametrize_entry_to_regex(entry) for entry in parametrize_entries
    ]
    actual_routes = _collect_actual_routes(repo_root)

    gaps: list[PiiRouteGap] = []
    seen_gap_paths: set[str] = set()
    for full_url, file, line in actual_routes:
        if not any(full_url.startswith(p) for p in _PII_PREFIXES):
            continue
        covered = any(
            pre.fullmatch(full_url) or pre.match(full_url + "/")
            for pre in parametrize_regexes
        )
        if covered:
            continue
        if full_url in seen_gap_paths:
            continue
        seen_gap_paths.add(full_url)
        gaps.append(
            PiiRouteGap(
                route_path=full_url,
                file=file,
                line=line,
                message=(
                    f"PII-shaped route {full_url!r} is not covered by any "
                    f"PII_ROUTES_PARAMETRIZE entry. Add the path (or a "
                    f"matching pattern) to "
                    f"tests/test_public_paths.py::PII_ROUTES_PARAMETRIZE."
                ),
            )
        )
    return gaps


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
        # Detector 13: query seam — fires only on service.py files
        # under app/modules/<M>/. Baselined legacy modules emit an
        # informational note (not a Violation); non-baselined modules
        # with _*_SQL but no queries.py emit a Violation.
        _violations = _check_query_seam_violation_on_path(path, tree, repo_root)
        out.extend(_violations)
        out.extend(_check_unjustified_lazy_import(path, tree))
    if _is_app_main_or_session(path, repo_root):
        out.extend(_check_csrf_samesite_strict(path, tree))
    if _is_app_main(path, repo_root):
        out.extend(_check_csrf_middleware_registered(path, tree))
    out.extend(_check_cross_module_import(path, tree, repo_root))
    if _is_route_file(path, repo_root):
        out.extend(_check_apap004_any_auth_dep(path, tree))
    return out


def _check_query_seam_violation_on_path(
    path: Path, tree: ast.Module, repo_root: Path
) -> list[Violation]:
    """Thin wrapper that guards _check_query_seam_violation to
    ``app/modules/<M>/service.py`` only. Returns only Violation objects
    (QuerySeamBaselineNote instances are informational and never block
    the gate — see :func:`find_query_seam_baseline_notes`)."""
    if path.name != "service.py":
        return []
    module_name = _own_module_name(path, repo_root)
    if module_name is None:
        return []
    results = _check_query_seam_violation(tree, module_name, path)
    return [r for r in results if isinstance(r, Violation)]


def find_query_seam_baseline_notes(
    repo_root: Path, exclude: frozenset[str] | None = None
) -> list[QuerySeamBaselineNote]:
    """Return the list of :class:`QuerySeamBaselineNote` informational
    records for the query seam detector.

    Mirrors the ``pii_route_coverage`` shape (informational scan that
    never blocks CI). Walks every ``app/modules/<M>/service.py`` under
    ``repo_root`` and emits one :class:`QuerySeamBaselineNote` per
    ``_*_SQL`` constant found in a module listed in
    :data:`BASELINE_NO_QUERIES_MODULES`. Baselined modules with SQL but
    no ``queries.py`` are grandfathered — the note exists so operators
    see how much legacy migration work remains to bring the codebase
    fully into compliance with §22.

    ``exclude`` honours the same prefix list as :func:`find_violations`
    (CLI ``--exclude`` / ``.check_rulesignore`` / ``DEFAULT_EXCLUDES``).
    Modules whose path matches an excluded prefix are silently skipped.

    Returns an empty list when no baselined module still carries SQL
    literals in ``service.py``.
    """
    excludes = exclude if exclude is not None else DEFAULT_EXCLUDES
    notes: list[QuerySeamBaselineNote] = []
    modules_root = repo_root / "app" / "modules"
    if not modules_root.is_dir():
        return notes
    for service_path in modules_root.rglob("service.py"):
        if _is_excluded(service_path, repo_root, excludes):
            continue
        module_name = _own_module_name(service_path, repo_root)
        if module_name is None:
            continue
        try:
            tree = ast.parse(
                service_path.read_text(encoding="utf-8"),
                filename=str(service_path),
            )
        except (SyntaxError, UnicodeDecodeError):
            continue
        results = _check_query_seam_violation(tree, module_name, service_path)
        for r in results:
            if isinstance(r, QuerySeamBaselineNote):
                notes.append(r)
    return notes


# Detector 1 -----------------------------------------------------------------


def _check_route_uses_execute_sql(path: Path, tree: ast.AST) -> list[Violation]:
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
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


def _is_route_file(path: Path, repo_root: Path) -> bool:
    """True if ``path`` is a FastAPI route file.

    Covers ``app/main.py`` and any ``routes*.py`` / ``batch_routes.py`` /
    ``assignment_routes.py`` under ``app/modules/<M>/``.
    """
    try:
        relative = path.relative_to(repo_root)
    except ValueError:
        return False
    if relative.parts == ("app", "main.py"):
        return True
    # app/modules/<M>/routes*.py or batch_routes.py or assignment_routes.py
    if (
        len(relative.parts) >= 3
        and relative.parts[0] == "app"
        and relative.parts[1] == "modules"
    ):
        name = relative.parts[-1]
        return (
            name.startswith("routes")
            or name == "batch_routes.py"
            or name == "assignment_routes.py"
        )
    return False


# Detector 14 (APAP004) ----------------------------------------------------


_USER_ANY_PARAM_RE = re.compile(r"\buser\s*:\s*Any\b")


def _check_integration_test_coverage(repo_root: Path) -> list[Violation]:
    """Detector 15 — issue #329.

    Reflection-based detector that enumerates every ``queries.py`` in
    ``app/modules/`` and fails if any exported ``build_*`` function lacks
    an integration test exercising it in ``tests/integration/``.

    The detection is reflection-based (not hardcoded):
      1. Walk ``app/modules/*/queries.py`` — collect all top-level function
         names starting with ``build_``.
      2. For each module, find ``tests/integration/test_<module>_queries_integration.py``
         (if it exists) OR ``tests/_rule_helpers/fixtures/detector15_<positive|negative>/``.
      3. Parse that test file and collect all ``def test_build_<name>`` names.
      4. Any ``build_*`` in the queries module without a matching
         ``test_build_*`` in the integration file is a violation.

    A module with no ``queries.py`` produces zero violations (the detector
    only fires for modules that have a queries.py).

    The detector runs at the repo level (not per-file) because it needs
    to cross-reference two different directory trees.
    """
    violations: list[Violation] = []
    modules_dir = repo_root / "app" / "modules"
    if not modules_dir.is_dir():
        return violations

    integration_dir = repo_root / "tests" / "integration"
    fixtures_dir = repo_root / "tests" / "_rule_helpers" / "fixtures"

    for queries_path in sorted(modules_dir.glob("*/queries.py")):
        module_name = queries_path.parent.name

        # 1. Collect all build_* functions from the queries module
        try:
            tree = ast.parse(queries_path.read_text(encoding="utf-8"), filename=str(queries_path))
        except (SyntaxError, UnicodeDecodeError):
            continue

        build_funcs: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                if node.name.startswith("build_"):
                    build_funcs.add(node.name)

        if not build_funcs:
            continue  # Nothing to check

        # 2. Find the corresponding integration test file (fixture root path
        # is checked so that Detector 15 itself can be tested with fixture files
        # that live outside the real tests/ tree and do not shadow the pytest
        # ``tests`` namespace package).
        integration_test_path = integration_dir / f"test_{module_name}_queries_integration.py"
        fixture_root_path: Path | None = None
        if fixtures_dir.is_dir():
            for fixture_dir in sorted(fixtures_dir.iterdir()):
                if not fixture_dir.is_dir():
                    continue
                candidate = fixture_dir / f"test_{module_name}_queries_integration.py"
                if candidate.exists():
                    fixture_root_path = candidate
                    break

        if not integration_test_path.exists() and fixture_root_path is None:
            # No integration test file at all — one violation per untested build_*
            for func_name in sorted(build_funcs):
                violations.append(
                    Violation(
                        file=queries_path,
                        line=1,
                        rule_id="integration_test_coverage",
                        message=(
                            f"Query function {func_name!r} in "
                            f"app/modules/{module_name}/queries.py has no integration test. "
                            f"Expected tests/integration/test_{module_name}_queries_integration.py "
                            f"to contain a test_{func_name} test. "
                            f"Issue #329: SQL must be validated against a real Postgres engine."
                        ),
                    )
                )
            continue

        # Use whichever was found (fixture root takes precedence if both exist,
        # which cannot happen in practice since module names differ)
        test_file = fixture_root_path if fixture_root_path else integration_test_path

        # 3. Parse the integration test file and collect test function names
        try:
            test_tree = ast.parse(
                test_file.read_text(encoding="utf-8"),
                filename=str(test_file),
            )
        except (SyntaxError, UnicodeDecodeError):
            # Parse error in the test file — skip rather than flagging
            # false violations. A separate test would catch the syntax error.
            continue

        tested_funcs: set[str] = set()
        for node in ast.walk(test_tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                if node.name.startswith("test_build_"):
                    # Extract the build function name: test_build_foo -> build_foo
                    tested_funcs.add(node.name[len("test_") :])

        # 4. Any build_* without a test_build_* is a violation
        for func_name in sorted(build_funcs - tested_funcs):
            violations.append(
                Violation(
                    file=queries_path,
                    line=1,
                    rule_id="integration_test_coverage",
                    message=(
                        f"Query function {func_name!r} in "
                        f"app/modules/{module_name}/queries.py has no integration test. "
                        f"Expected test_{func_name!r} in "
                        f"tests/integration/test_{module_name}_queries_integration.py. "
                        f"Issue #329: SQL must be validated against a real Postgres engine."
                    ),
                )
            )

    return violations


def _check_apap004_any_auth_dep(path: Path, tree: ast.AST) -> list[Violation]:
    """Detector 14 — APAP004.

    Flags ``user: Any`` in FastAPI route handler parameters. The ``Any``
    annotation erases the mypy type boundary at the auth surface: routes
    that accept ``user: Any = Depends(...)`` lose all type information about
    the authenticated-user payload (user_id, email, rol, is_authorized).
    Replace with ``user: AuthenticatedUser`` imported from
    ``app.core.auth_dependencies``.

    Scope: ``app/main.py`` and any ``routes*.py`` / ``batch_routes.py`` /
    ``assignment_routes.py`` under ``app/modules/<M>/``.
    """
    violations: list[Violation] = []
    src = path.read_text(encoding="utf-8")
    for lineno, line in enumerate(src.splitlines(), start=1):
        stripped = line.strip()
        # Skip comment-only lines
        if stripped.startswith("#"):
            continue
        if _USER_ANY_PARAM_RE.search(line):
            violations.append(
                Violation(
                    file=path,
                    line=lineno,
                    rule_id="apap004_any_auth_dep",
                    message=(
                        "user: Any in route handler parameter erases the auth "
                        "type boundary. Replace with 'user: AuthenticatedUser' "
                        "from app.core.auth_dependencies (APAP004)."
                    ),
                )
            )
    return violations


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

    The CSRF middleware MUST be wired into the FastAPI middleware
    chain. Catches accidental removal of the gate.

    Issue #204 moved the chain registration from ``app/main.py`` to
    :func:`app.core.middleware.install_auth_middleware`. The detector
    therefore checks TWO surfaces on two distinct files:

    - ``app/core/middleware.py`` MUST contain ``CsrfMiddleware``
      (the class reference), so the registration is wired inside
      the install function.
    - ``app/main.py`` MUST call ``install_auth_middleware`` (the
      function name as a literal), so the wiring actually runs at
      app boot. This is the transitively-loaded counterpart to the
      first check.

    Both surfaces are required: dropping the class in middleware.py
    fails the first check; dropping the installer call in main.py
    fails the second. The two surfaces together close the same
    regression window the original Detector 7 covered.
    """
    # Resolve the two files the detector watches. We do not depend on
    # the surrounding ``_scan_file`` scope for repo_root; this detector
    # walks absolute paths only.
    repo_root = _find_repo_root(path)
    app_main = repo_root / "app" / "main.py"
    app_core_middleware = repo_root / "app" / "core" / "middleware.py"
    src = path.read_text(encoding="utf-8")
    if path == app_main:
        if "install_auth_middleware" in src:
            return []
        return [
            Violation(
                file=path,
                line=1,
                rule_id="csrf_middleware_registered",
                message=(
                    "app/main.py does not call install_auth_middleware(). "
                    "Issue #204 moved the CSRF (and UA) registration into "
                    "app.core.middleware.install_auth_middleware; call it "
                    "from create_app() so the CSRF gate is wired. "
                    "Rule 10: CSRF defense per default."
                ),
            )
        ]
    if path == app_core_middleware:
        if "CsrfMiddleware" in src:
            return []
        return [
            Violation(
                file=path,
                line=1,
                rule_id="csrf_middleware_registered",
                message=(
                    "app/core/middleware.py does not register CsrfMiddleware. "
                    "Issue #204 expects "
                    "`install_auth_middleware(app, settings)` to call "
                    "`app.add_middleware(CsrfMiddleware)` (gated on "
                    "`settings.csrf_enabled`). "
                    "Rule 10: CSRF defense per default."
                ),
            )
        ]
    return []


def _find_repo_root(path: Path) -> Path:
    """Walk up from ``path`` until we find the directory containing
    ``app/``. Used by Detector 7 only; the rest of the linter uses
    the repo_root passed by the CLI loop.
    """
    here = path if path.is_dir() else path.parent
    for candidate in (here, *here.parents):
        if (candidate / "app").is_dir():
            return candidate
    # Fallback: assume the path's parent chain already has the right
    # structure; the worst case is the walk above didn't find a
    # marker and we return the file's enclosing directory.
    return here


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


# Detector 13 (Rule 22) -------------------------------------------------


def _lower_first_literal(value_node: ast.expr) -> str | None:
    """Extract the first string literal from a Constant, JoinedStr, or BinOp.

    Handles three AST shapes that can produce a string value:

    - ``ast.Constant`` with a ``str`` value (plain string).
    - ``ast.JoinedStr`` (f-string with one literal segment — the common
      case for SQL constants in this codebase).
    - ``ast.BinOp`` with ``ast.Add`` of two string constants (less common
      but present in some SQL templates built with ``+``).

    Returns the string lowercased and whitespace-stripped, or ``None``
    if the node is not one of the above shapes.
    """
    if isinstance(value_node, ast.Constant) and isinstance(value_node.value, str):
        return value_node.value.lower().strip()
    if isinstance(value_node, ast.JoinedStr):
        # JoinedStr: walk the values; collect the literal parts.
        parts: list[str] = []
        for node in value_node.values:
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                parts.append(node.value)
        if parts:
            return "".join(parts).lower().strip()
        return None
    if isinstance(value_node, ast.BinOp) and isinstance(value_node.op, ast.Add):
        left = _lower_first_literal(value_node.left)
        right = _lower_first_literal(value_node.right)
        if left is not None and right is not None:
            return (left + right).strip()
    return None


_SQL_KEYWORDS: frozenset[str] = frozenset(
    {"select", "insert", "update", "delete", "with"}
)


def _is_sql_keyword_prefix(text: str) -> bool:
    """Return True iff ``text`` starts with a SQL keyword.

    Used to decide whether a string constant in ``service.py`` looks like
    a SQL statement (and therefore should live in ``queries.py`` per
    Rule §22). The check is case-insensitive and strips leading
    whitespace.
    """
    stripped = text.strip().lower()
    return any(stripped.startswith(kw) for kw in _SQL_KEYWORDS)


def _has_queries_py(module_dir: Path) -> bool:
    """Return True iff ``module_dir / 'queries.py'`` exists."""
    return (module_dir / "queries.py").is_file()


def _own_module_name(path: Path, repo_root: Path) -> str | None:
    """Return the domain module name for a path under ``app/modules/<M>/``."""
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        return None
    parts = rel.parts
    if len(parts) >= 3 and parts[0] == "app" and parts[1] == "modules":
        return parts[2]
    return None


def _check_query_seam_violation(
    tree: ast.Module, module_name: str, file_path: Path
) -> list[Violation | QuerySeamBaselineNote]:
    """Detector 13 — Rule 22.

    Scans a single ``service.py`` file for ``_*_SQL`` constants.

    - If the module's ``queries.py`` exists: module is migrated, no output.
    - Baselined legacy modules (``BASELINE_NO_QUERIES_MODULES``):
      emit ``QuerySeamBaselineNote`` (informational) so operators know
      how much grandfathered legacy remains. No ``Violation``.
    - Non-baselined modules with ``_*_SQL`` but no ``queries.py``:
      emit ``Violation`` with ``rule_id = "query_seam_violation"``.
    - Non-baselined modules with ``_*_SQL`` AND ``queries.py``:
      no violation (module follows §22 correctly).
    - Any module with no ``_*_SQL`` at all: no violation, no note.

    The detector only fires for ``service.py`` files. Sibling files
    like ``batch_service.py`` are intentionally not checked.
    """
    # If queries.py exists, the module is migrated — no output regardless
    # of baseline status.
    module_dir = file_path.parent
    if _has_queries_py(module_dir):
        return []
    results: list[Violation | QuerySeamBaselineNote] = []
    is_baselined = module_name in BASELINE_NO_QUERIES_MODULES

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if not node.targets or not isinstance(node.targets[0], ast.Name):
                continue
            name = node.targets[0].id
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            if not isinstance(node.target, ast.Name):
                continue
            name = node.target.id
            value = node.value
        else:
            continue
        if not name.endswith("_SQL"):
            continue
        first_lit = _lower_first_literal(value)
        if first_lit is None:
            continue
        if not _is_sql_keyword_prefix(first_lit):
            continue
        # This assignment is a _*_SQL constant with SQL keyword value.
        if is_baselined:
            results.append(
                QuerySeamBaselineNote(
                    module_name=module_name,
                    file=file_path,
                    line=node.lineno,
                    message=(
                        f"Module {module_name!r} is in "
                        f"BASELINE_NO_QUERIES_MODULES and has "
                        f"{name!r} in service.py. "
                        f"Migration: extract to queries.py and remove "
                        f"from the baseline (issue #290)."
                    ),
                )
            )
        else:
            results.append(
                Violation(
                    file=file_path,
                    line=node.lineno,
                    rule_id="query_seam_violation",
                    message=(
                        f"service.py has {name!r} "
                        f"(SQL literal) but no queries.py seam. "
                        f"Rule §22: move SQL to "
                        f"app/modules/{module_name}/queries.py "
                        f"and import the builder here."
                    ),
                )
            )
    return results


# Detector 10 (Rule 25) -------------------------------------------------
#
# ``duplicate_helper_definition`` — a watch-list regression guard, NOT a
# general duplicate-code detector. The 2026-07-20 architecture review
# found ``_opt`` copied near-identically into a dozen ``routes.py`` /
# ``service.py`` files and ``_required_text`` / ``_optional_text``
# reimplemented in eight ``service.py`` files (each self-documented in
# comments as "mirrors X" — the duplication was noticed and left
# anyway). Issue #227 tracks consolidating them into one shared module;
# this detector's job is to make sure the SAME pattern doesn't reappear
# with a thirteenth file (or a brand-new shared-helper name) while #227
# is still open.

#: Function names known to have been duplicated across app/ modules.
#: Grows over time as new shared helpers get established and then
#: (inevitably) copy-pasted once before someone notices.
WATCHED_DUPLICATE_HELPERS: frozenset[str] = frozenset(
    {"_opt", "_required_text", "_optional_text"}
)

#: Ratchet baseline: files where a watched helper name is ALREADY known
#: to be duplicated (2026-07-20 audit, issue #227). Entries may only
#: shrink as #227 lands — removing a file from a name's set, or
#: removing the name entirely once only one definition remains. Never
#: add a NEW file here: extract the shared helper into one module
#: instead of grandfathering another copy.
BASELINE_DUPLICATE_HELPERS: dict[str, frozenset[str]] = {
    "_opt": frozenset(
        {
            "app/modules/voluntarios/service.py",
            "app/modules/voluntarios/routes.py",
            "app/modules/cesiones/routes.py",
            "app/modules/sanidad/routes.py",
            "app/modules/entradas/batch_routes.py",
            "app/modules/adopciones/routes.py",
            "app/modules/acogidas/routes.py",
        }
    ),
    "_required_text": frozenset(
        {
            "app/modules/adopciones/service.py",
            "app/modules/acogidas/service.py",
            "app/modules/cesiones/service.py",
            "app/modules/entradas/batch_service.py",
            "app/modules/sanidad/service.py",
        }
    ),
    "_optional_text": frozenset(
        {
            "app/modules/adopciones/service.py",
            "app/modules/acogidas/service.py",
            "app/modules/cesiones/service.py",
            "app/modules/entradas/batch_service.py",
            "app/modules/sanidad/service.py",
        }
    ),
}


def _iter_app_python_files(repo_root: Path) -> list[Path]:
    """Yield every Python file under ``repo_root/app``.

    Shared by Detectors 10 and 12 (both scoped to ``app/``, not the
    whole repo). Mirrors :func:`_iter_app_route_files`.
    """
    app_dir = repo_root / "app"
    if not app_dir.exists():
        return []
    return sorted(
        p for p in app_dir.rglob("*.py") if not (set(p.parts) & _EXCLUDED_PARTS)
    )


def _check_duplicate_helper_definitions(repo_root: Path) -> list[Violation]:
    """Detector 10 — Rule 25.

    Scans every file under ``repo_root/app`` for top-level or nested
    ``def``/``async def`` matching a name in
    :data:`WATCHED_DUPLICATE_HELPERS`. If a watched name is DEFINED
    (not merely called or imported) in more than one file, every
    defining file that is NOT already accounted for in
    :data:`BASELINE_DUPLICATE_HELPERS` is a violation — i.e. this only
    re-flags NEW drift beyond the already-tracked (#227) duplication.
    """
    definitions: dict[str, list[tuple[Path, int]]] = {
        name: [] for name in WATCHED_DUPLICATE_HELPERS
    }
    for path in _iter_app_python_files(repo_root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        seen_in_file: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if node.name not in WATCHED_DUPLICATE_HELPERS or node.name in seen_in_file:
                continue
            seen_in_file.add(node.name)
            definitions[node.name].append((path, node.lineno))

    violations: list[Violation] = []
    for name, occurrences in definitions.items():
        if len(occurrences) <= 1:
            continue
        baseline_files = BASELINE_DUPLICATE_HELPERS.get(name, frozenset())
        for path, lineno in occurrences:
            try:
                rel = path.relative_to(repo_root).as_posix()
            except ValueError:
                rel = str(path)
            if rel in baseline_files:
                continue
            violations.append(
                Violation(
                    file=path,
                    line=lineno,
                    rule_id="duplicate_helper_definition",
                    message=(
                        f"'{name}' is defined here AND in {len(occurrences) - 1} "
                        f"other file(s) under app/ (watch-list: "
                        f"{sorted(WATCHED_DUPLICATE_HELPERS)}). Rule 25: extract "
                        f"the shared helper into one module instead of copying "
                        f"it again (see issue #227)."
                    ),
                )
            )
    return violations


# Detector 11 (Rule 26) -------------------------------------------------
#
# ``unjustified_lazy_import`` — the 2026-07-20 review found two
# independent function/property-body imports used to dodge a
# module-level circular import (``app/core/config.py`` importing
# ``Rol`` from ``auth.py`` inside a property; ``app/core/
# auth_dependencies.py`` importing ``get_user_by_email`` from
# ``auth.py`` inside a function), tracked as issue #226. Rule 26
# requires every local (function/method-body) import under ``app/`` to
# carry a ``lazy-import:`` marker on its own line or the line before,
# explaining WHY it isn't hoisted to module level.


class _FunctionScopeImportVisitor(ast.NodeVisitor):
    """Collect ``Import``/``ImportFrom`` nodes whose nearest enclosing
    scope is a function (not module level). Class bodies do not open a
    new "scope" for this purpose (an import directly in a class body is
    still effectively module-load-time), only ``def``/``async def``.
    """

    def __init__(self) -> None:
        self.depth = 0
        self.found: list[ast.Import | ast.ImportFrom] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.depth += 1
        self.generic_visit(node)
        self.depth -= 1

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.depth += 1
        self.generic_visit(node)
        self.depth -= 1

    def visit_Import(self, node: ast.Import) -> None:
        if self.depth > 0:
            self.found.append(node)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if self.depth > 0:
            self.found.append(node)
        self.generic_visit(node)


_LAZY_IMPORT_MARKER = "lazy-import:"


def _check_unjustified_lazy_import(path: Path, tree: ast.AST) -> list[Violation]:
    """Detector 11 — Rule 26. Only called for files under ``app/``."""
    visitor = _FunctionScopeImportVisitor()
    visitor.visit(tree)
    if not visitor.found:
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    violations: list[Violation] = []
    for node in visitor.found:
        lineno = node.lineno
        own_line = lines[lineno - 1] if 0 < lineno <= len(lines) else ""
        prev_line = lines[lineno - 2] if lineno >= 2 else ""
        marker_lines = (own_line, prev_line)
        if any(
            line.partition(_LAZY_IMPORT_MARKER)[2].strip()
            for line in marker_lines
            if _LAZY_IMPORT_MARKER in line
        ):
            continue
        kind = "import" if isinstance(node, ast.Import) else "from-import"
        violations.append(
            Violation(
                file=path,
                line=lineno,
                rule_id="unjustified_lazy_import",
                message=(
                    f"Local {kind} inside a function/method body has no "
                    f"'{_LAZY_IMPORT_MARKER}' justification. Rule 26: either "
                    f"hoist it to module level, or add a trailing (or "
                    f"preceding) comment explaining why it must stay lazy "
                    f"(e.g. '# lazy-import: avoids circular import with "
                    f"app.core.X')."
                ),
            )
        )
    return violations


# Detector 12 (Rule 27) -------------------------------------------------
#
# ``cross_module_submodule_import`` / ``cross_module_private_import`` —
# the 2026-07-20 dependency-map audit found this project is an almost
# clean DAG of domain modules (most import nothing from each other).
# The two exceptions found: ``app/modules/foster/assignment.py``
# importing ``app.modules.animals.service`` directly (bypassing
# ``animals/__init__.py``, which exposes no public API — issue #231),
# and an equivalent shorthand-submodule import from ``acogidas/routes.py``
# into ``foster.assignment`` (fixed in this same PR, see AGENTS.md rule
# 27). This detector keeps the DAG clean as the project grows to more
# modules.

#: Ratchet allowlist: (file, imported dotted module) pairs that are
#: ALREADY known cross-module submodule-reach violations, tracked by an
#: open issue. May only shrink (an entry is removed once its target
#: module grows a real public API and the import is fixed) — never add
#: a new entry: fix the target module's ``__init__.py`` instead.
BASELINE_CROSS_MODULE_IMPORTS: frozenset[tuple[str, str]] = frozenset()


def _own_app_modules_name(path: Path, repo_root: Path) -> str | None:
    """Return the domain module name (``animals``, ``foster``, ...) that
    ``path`` belongs to, or ``None`` if ``path`` is not under
    ``app/modules/<name>/``.
    """
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        return None
    parts = rel.parts
    if len(parts) >= 3 and parts[0] == "app" and parts[1] == "modules":
        return parts[2]
    return None


def _check_cross_module_import(
    path: Path, tree: ast.AST, repo_root: Path
) -> list[Violation]:
    """Detector 12 — Rule 27. Only fires for files under
    ``app/modules/<A>/`` importing from ``app/modules/<B>/`` (A != B).
    """
    own_module = _own_app_modules_name(path, repo_root)
    if own_module is None:
        return []
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules = [alias.name for alias in node.names]
            import_names: list[ast.alias] = []
        elif isinstance(node, ast.ImportFrom):
            if node.level or not node.module:
                continue
            imported_modules = [node.module]
            import_names = node.names
        else:
            continue

        for imported_module in imported_modules:
            if not imported_module.startswith("app.modules."):
                continue
            violations.extend(
                _cross_module_import_violations(
                    path, node, imported_module, import_names, own_module, repo_root
                )
            )
    return violations


def _cross_module_import_violations(
    path: Path,
    node: ast.Import | ast.ImportFrom,
    imported_module: str,
    import_names: list[ast.alias],
    own_module: str,
    repo_root: Path,
) -> list[Violation]:
    violations: list[Violation] = []
    segments = imported_module.split(".")
    if len(segments) < 3:
        return []
    target_module = segments[2]
    if target_module == own_module:
        return []  # same-module import: rule 27 is cross-module only
    try:
        rel = path.relative_to(repo_root).as_posix()
    except ValueError:
        rel = str(path)
    if (rel, imported_module) in BASELINE_CROSS_MODULE_IMPORTS:
        return []

    reaches_submodule = len(segments) > 3
    if not reaches_submodule:
        # Shorthand form: ``from app.modules.<target> import <name>``
        # where <name> is itself a submodule file/package of
        # <target> (Python's import machinery resolves this exactly
        # like a submodule path, even though the AST module string
        # is just ``app.modules.<target>``).
        target_dir = repo_root / "app" / "modules" / target_module
        for alias in import_names:
            if (target_dir / f"{alias.name}.py").is_file() or (
                target_dir / alias.name / "__init__.py"
            ).is_file():
                reaches_submodule = True
                break

    if reaches_submodule:
        violations.append(
            Violation(
                file=path,
                line=node.lineno,
                rule_id="cross_module_submodule_import",
                message=(
                    f"Cross-module import reaches into "
                    f"'{imported_module}' submodule directly. Rule 27: "
                    f"import from the package app.modules."
                    f"{target_module} (its __init__.py public API), "
                    f"never a submodule path."
                ),
            )
        )

    private_names = [a.name for a in import_names if a.name.startswith("_")]
    if private_names:
        violations.append(
            Violation(
                file=path,
                line=node.lineno,
                rule_id="cross_module_private_import",
                message=(
                    f"Cross-module import of private name(s) "
                    f"{private_names} from '{imported_module}'. Rule 27: "
                    f"never import a name starting with '_' across "
                    f"module boundaries, regardless of source."
                ),
            )
        )
    return violations

# Guard: nested-checkout detection ---------------------------------------------
#
# The APAP_WEB layout uses git-worktree: 00_main/ is the canonical worktree,
# sibling worktrees live under APAP_WEB_worktrees/, and the repo root
# APAP_WEB/ has .git as a FILE (gitdir: 00_main/.git). Running
# check_rules.py from APAP_WEB/ causes rglob to walk into nested
# checkouts and report false violations. The guard below detects this
# layout and fails fast with a clear message instead.


def _check_nested_checkout_layout(cwd: Path) -> str | None:
    """Return an error message if ``cwd`` is the APAP_WEB/ root with nested
    checkouts, otherwise None.

    Detection heuristic: ``cwd / '00_main'`` is a directory AND
    ``cwd / '.git'`` is a FILE (not a directory) — the signature of a
    git-worktree root. Operators running from APAP_WEB/ (the flat-layout
    root, not 00_main/) will hit this guard and see the directive to
    cd to 00_main/.
    """
    if (cwd / "00_main").is_dir() and (cwd / ".git").is_file():
        return (
            "check_rules.py must be run from the canonical worktree (00_main/),\n"
            "not from the APAP_WEB/ root. The root contains sibling worktrees\n"
            "that produce false rule violations when scanned.\n"
            "\n"
            "  Run: cd 00_main/ (or a sibling worktree under APAP_WEB_worktrees/)\n"
            "  Then: python scripts/check_rules.py .\n"
            "\n"
            "The linter detects it is being run from the flat-layout root and\n"
            "refuses to produce false violations. Fix: run from 00_main/."
        )
    return None


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

    # Guard: detect and refuse the flat-layout root (APAP_WEB/) which
    # contains sibling worktrees that produce false rule violations.
    guard_msg = _check_nested_checkout_layout(Path.cwd())
    if guard_msg:
        print(guard_msg, file=sys.stderr)
        return 1

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
    # Determine the repo root ONCE so every informational detector
    # (``pii_route_coverage`` + ``query_seam_baseline_note``) reads the
    # same view of the tree. Use the first scanned path's parent if it
    # looks like the repo root (so ``scripts/check_rules.py .`` still
    # works); for ``scripts/check_rules.py app`` the repo root is the
    # cwd.
    repo_root = Path.cwd()
    if paths:
        first_path = paths[0].resolve()
        if (first_path / "tests/test_public_paths.py").exists():
            repo_root = first_path
    # PR5 informational detector: ``pii_route_coverage`` emits WARNINGs
    # that surface drift between ``app/`` routes and the
    # ``PII_ROUTES_PARAMETRIZE`` tuple. Warnings are printed to stdout
    # and never block the gate; they exist so the next operator pass
    # notices a new PII-shaped route that wasn't added to the
    # parametrize list. The detector reads the parametrize tuple from
    # the REPO ROOT (not the scanned path) because ``PII_ROUTES_PARAMETRIZE``
    # lives at ``<repo_root>/tests/test_public_paths.py``. The app/ scan
    # covers the route side of the comparison.
    pii_gaps: list[PiiRouteGap] = []
    pii_gaps.extend(find_pii_route_gaps(repo_root))
    if pii_gaps:
        for gap in sorted(pii_gaps, key=lambda x: x.route_path):
            location = (
                f"{gap.file}:{gap.line}" if gap.file else "(no source)"
            )
            print(
                f"WARNING ({gap.rule_id}): {gap.route_path} [{location}] \u2014 "
                f"{gap.message}"
            )
        print(
            f"\n{len(pii_gaps)} pii_route_coverage warning(s); "
            f"informational, does NOT block CI.",
            file=sys.stdout,
        )
    # Detector 13 informational notes: ``query_seam_baseline_note``
    # surfaces the modules in ``BASELINE_NO_QUERIES_MODULES`` that still
    # carry ``_*_SQL`` constants in ``service.py`` (issue #290 migration
    # backlog). Like ``pii_route_coverage``, the notes never block CI;
    # they exist so the operator sees how much grandfathered legacy
    # remains to be migrated into the §22 ``queries.py`` seam.
    seam_notes: list[QuerySeamBaselineNote] = []
    seam_notes.extend(find_query_seam_baseline_notes(repo_root, exclude=excludes))
    if seam_notes:
        for note in sorted(seam_notes, key=lambda x: (x.module_name, x.line)):
            print(
                f"INFO ({note.rule_id}): {note.module_name} "
                f"[{note.file}:{note.line}] \u2014 {note.message}"
            )
        print(
            f"\n{len(seam_notes)} query_seam_baseline_note(s); "
            f"informational, does NOT block CI.",
            file=sys.stdout,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
