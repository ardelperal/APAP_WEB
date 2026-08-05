"""Filtered vulture dead-code guard.

Issue #392: a filtered vulture pipeline wired into CI with a frozen
baseline, following the ``check_ruff_ratchet.py`` pattern.

The problem with raw vulture output is that ~90 % of findings are
framework-driven false positives:
- Route handlers (decorated with ``@router.get`` etc.) are reported as
  "unused" even though FastAPI wires them via the decorator.
- Pytest fixtures and test helpers are reported as "unused" when scanned
  together with production code.

This guard applies a three-stage filter:

1. AST drop — any symbol whose definition node has a non-empty
   ``decorator_list`` is discarded (routes, pytest fixtures, etc.).
2. Name drop — names matching ``_protected_names`` (``dispatch``,
   ``__enter__``, ``__exit__``, ``__getattr__``, and any name starting
   with ``pytest_``) are discarded.
3. Cross-reference check — every remaining symbol must appear more than
   once in the scanned tree.  A symbol defined once and never referenced
   elsewhere is confirmed dead.

The BASELINE was measured on ``main @54bbbf7`` before the #392 deletions
and frozen at 5. Every PR that introduces a new confirmed-dead symbol
must either delete it or raise the baseline (the ratchet only hardens,
never relaxes).

Usage::

    python scripts/check_vulture_guard.py [root]

``root`` defaults to the repository root (the parent of ``scripts/``).
Exit code 0 when dead-symbol count <= BASELINE, 1 when it exceeds it.

Issue: #392
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

#: Packages vulture scans for *candidates*.  ``tests`` is deliberately absent:
#: a pytest fixture is referenced by parameter name, a module-level constant by
#: import, and neither reads as a use to any static scanner.  Reporting dead
#: symbols inside ``tests`` produced 13 false positives on the tree this guard
#: was built against, and a gate that cries wolf is switched off within a week.
REPORT_SCOPE: tuple[str, ...] = ("app", "migration", "scripts")

#: Packages scanned for *references*.  ``tests`` IS included here — that is the
#: half of issue #392's "scan production and tests together" that matters: a
#: production helper exercised only by the suite is not dead.
REFERENCE_SCOPE: tuple[str, ...] = ("app", "migration", "scripts", "tests")

#: Names that are framework contracts even when they appear unused.
_PROTECTED_NAMES: frozenset[str] = frozenset({
    "dispatch",
    "__enter__",
    "__exit__",
    "__getattr__",
})

#: BASELINE dead-symbol count, measured on main @e4b0a80 *after* the three
#: defects in #424 were fixed.  #392 shipped 5 here immediately after deleting
#: those same 5, which would have admitted five new dead symbols without
#: failing — AGENTS.md §32.P7, "guards that cancel themselves".  This value is
#: the count the working guard actually reports, not a number chosen to pass.
#:
#: The 3 grandfathered symbols, each verified to have exactly one occurrence in
#: the tree (its own definition).  Triage tracked separately; they are NOT an
#: allowance for new ones:
#:   app/main.py                 '_DISABLED_DOC_PATHS'  (deliberate re-export)
#:   app/modules/salud/service.py 'TerapiaNotFoundError'
#:   scripts/fix_form_labels.py   'is_void_tag'
#:
#: Every value may only decrease.  Raising the baseline requires an
#: explicit rationale in the same commit (the ratchet never relaxes).
BASELINE: int = 3


def collect_referenced_names(root: Path) -> set[str]:
    """Return every identifier that is *used* anywhere under REFERENCE_SCOPE.

    This is the stage issue #392 called "confirmed dead = appears exactly once
    in the full scan" and that the first implementation never built: it counted
    occurrences inside vulture's own findings list, where each definition
    appears exactly once by construction, so the check was always true.

    The collection is deliberately generous — ``Name``, attribute names,
    parameter names and plain string literals all count as a reference. String
    literals matter because ``__all__`` re-exports, ``getattr`` and
    ``monkeypatch.setattr`` targets name symbols without ever producing a
    ``Name`` node.

    That bias is the right one for a ratchet. A false negative means one dead
    symbol survives another cycle; a false positive means a green build turns
    red for a symbol that is actually in use, and the gate gets disabled. The
    guard exists to stop dead code *accumulating*, not to prove its absence.

    Definitions do not count as references: ``def foo`` is a ``FunctionDef``
    node carrying ``.name``, never a ``Name`` load, so a symbol whose only
    appearance is its own definition is correctly left in the candidate set.
    """
    referenced: set[str] = set()
    for part in REFERENCE_SCOPE:
        base = root / part
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError, OSError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    referenced.add(node.id)
                elif isinstance(node, ast.Attribute):
                    referenced.add(node.attr)
                elif isinstance(node, ast.arg):
                    referenced.add(node.arg)
                elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                    referenced.add(node.value)
    return referenced


def _ast_definitions(source: str) -> dict[int, tuple[str, list[str]]]:
    """Return {line: (symbol_type, [decorator_names])} for every
    FunctionDef/AsyncFunctionDef/ClassDef in ``source``.

    The value is the raw decorator name strings (dotted or simple) so callers
    can apply additional filters without re-parsing.
    """
    out: dict[int, tuple[str, list[str]]] = {}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_") and not node.name.startswith("__"):
                # Leading-underscore "private" helpers are still candidates
                # unless they are framework hooks.
                pass
            # Record the *definition* line, not the first decorator line.
            # Vulture reports the decorator line for decorated functions, which
            # is why we use the def node's line here and match by scanning
            # backward from vulture's reported line to the nearest def.
            out[node.lineno] = ("function", [
                d.attr if isinstance(d, ast.Attribute)
                else getattr(d, "id", "") or "" for d in node.decorator_list
            ])
        elif isinstance(node, ast.ClassDef):
            out[node.lineno] = ("class", [
                d.attr if isinstance(d, ast.Attribute)
                else getattr(d, "id", "") or "" for d in node.decorator_list
            ])
    return out


def _decorator_line_index(source: str) -> dict[int, int]:
    """Return {decorator_lineno: def_lineno} for every decorated definition.

    Vulture reports the line of the *first decorator*, and the ``def`` sits
    **below** it. Resolving that by walking backward through the text can
    never reach the ``def``, and resolving it by walking forward breaks on
    multi-line decorators such as ``@pytest.mark.parametrize(\\n ... \\n)``.

    Both failure modes have the same consequence: the decorator filter never
    fires, so every FastAPI route handler and every pytest fixture is reported
    as dead. That is the exact trap issue #392 documented, and the reason it
    requires the AST rather than a textual scan: ``node.lineno`` is already the
    ``def`` line and ``node.decorator_list`` carries each decorator's own line.
    """
    index: dict[int, int] = {}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return index
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for dec in node.decorator_list:
                index[dec.lineno] = node.lineno
    return index


def _find_def_line(source_lines: list[str], reported_lineno: int) -> int:
    """Return the line number of the actual def/class statement.

    ``source_lines`` is kept in the signature so the helper stays usable for
    undecorated symbols, where vulture already points at the ``def`` itself.
    Decorated symbols are resolved through the AST index built by
    :func:`_decorator_line_index`.
    """
    source = "\n".join(source_lines)
    return _decorator_line_index(source).get(reported_lineno, reported_lineno)


def _is_protected_name(name: str) -> bool:
    """Return True for framework-contract names that should be excluded."""
    return name in _PROTECTED_NAMES or name.startswith("pytest_")


def parse_vulture_output(output: str) -> list[tuple[str, int, str]]:
    """Parse vulture stdout and return [(filepath, lineno, symbol_name)].

    Ignores the "dead" classification and confidence from vulture; the guard
    applies its own cross-reference filter instead.
    """
    findings: list[tuple[str, int, str]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        # vulture emits a TYPE word between "unused" and the quoted symbol:
        #   <path>:<lineno>: unused <class|function|variable|...> '<sym>' (N% confidence)
        # Omitting that word makes the pattern match nothing at all, which
        # turns the whole guard into a no-op that passes with any amount of
        # dead code (AGENTS.md §32.P7). Pinned by test_check_vulture_guard.py.
        # The optional ``[A-Za-z]:`` prefix is not cosmetic. vulture prints
        # RELATIVE paths when the target sits under the cwd and ABSOLUTE ones
        # otherwise, so on Windows the drive-letter colon lands inside the
        # path group. A ``[^\n:]+`` path pattern therefore parses fine in CI
        # (cwd = repo root) and nothing at all anywhere else — which is what
        # made this guard impossible to test in isolation, and is how the
        # defects above survived review.
        m = re.match(
            r"^((?:[A-Za-z]:)?[^\n:]+):(\d+):\s+unused\s+\w+\s+'([^']+)'", line
        )
        if m:
            findings.append((m.group(1), int(m.group(2)), m.group(3)))
    return findings


def _load_source(path: Path) -> tuple[list[str], dict[int, tuple[str, list[str]]]]:
    """Return (lines_list, defs_dict) for ``path``."""
    source = path.read_text(encoding="utf-8")
    return source.splitlines(), _ast_definitions(source)


def _decorated(defs: dict[int, tuple[str, list[str]]], def_lineno: int) -> bool:
    """Return True when the def/class at ``def_lineno`` has decorators."""
    info = defs.get(def_lineno)
    if info is None:
        return False
    return bool(info[1])


def _run_vulture(root: Path) -> tuple[list[tuple[str, int, str]], str | None]:
    """Run vulture over REPORT_SCOPE and return (findings, error)."""
    targets = [str(root / part) for part in REPORT_SCOPE if (root / part).is_dir()]
    cmd = [sys.executable, "-m", "vulture", *targets]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, check=False
        )
    except OSError as exc:
        return [], f"cannot run vulture ({exc})"

    # vulture exits 0 when nothing is found, 1 when dead code is found.
    # Treat both as normal; only an OSError is a real failure.
    return parse_vulture_output(proc.stdout), None


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    root = Path(args[0]).resolve() if args else Path(__file__).resolve().parents[1]

    findings, error = _run_vulture(root)
    if error is not None:
        print(f"FAIL check_vulture_guard: {error}")
        return 1

    # Pre-load every source file that vulture mentioned, indexed by path.
    source_cache: dict[str, tuple[list[str], dict[int, tuple[str, list[str]]]]] = {}
    for filepath, _lineno, _name in findings:
        if filepath not in source_cache:
            full = root / filepath
            if full.exists():
                source_cache[filepath] = _load_source(full)

    referenced = collect_referenced_names(root)

    dead_symbols: list[str] = []
    for filepath, lineno, name in findings:
        if _is_protected_name(name):
            continue

        # Resolve vulture's reported line (the first DECORATOR for decorated
        # symbols) to the actual def, then drop anything decorated: the
        # decorator is the reference, so FastAPI routes and pytest fixtures
        # are never dead even though nothing calls them by name.
        if filepath in source_cache:
            lines, defs = source_cache[filepath]
            actual_def_line = _find_def_line(lines, lineno)
            if _decorated(defs, actual_def_line):
                continue

        # Cross-reference against the source tree — including tests, so a
        # production helper exercised only by the suite is not reported.
        if name in referenced:
            continue

        dead_symbols.append(f"{filepath}:{lineno} '{name}'")

    count = len(dead_symbols)

    if count > BASELINE:
        print(f"FAIL check_vulture_guard: {count} confirmed-dead symbol(s), exceeds BASELINE of {BASELINE}")
        for sym in sorted(dead_symbols):
            print(f"  {sym}")
        print("  Delete the symbol(s) above or update BASELINE in scripts/check_vulture_guard.py")
        return 1

    print(f"check_vulture_guard: OK ({count} confirmed-dead symbol(s), within BASELINE of {BASELINE})")
    if count < BASELINE:
        print(f"  NOTE: {BASELINE - count} below BASELINE — update BASELINE to lock in the improvement")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
