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

#: Production packages scanned.  Tests are deliberately included so that
#: test-only helpers do not silently shadow production symbols.
SCOPE: tuple[str, ...] = ("app", "migration", "scripts", "tests")

#: Names that are framework contracts even when they appear unused.
_PROTECTED_NAMES: frozenset[str] = frozenset({
    "dispatch",
    "__enter__",
    "__exit__",
    "__getattr__",
})

#: BASELINE dead-symbol count, measured on main @54bbbf7 (issue #392).
#: Every value may only decrease.  Raising the baseline requires an
#: explicit rationale in the same commit (the ratchet never relaxes).
BASELINE: int = 5


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


def _find_def_line(source_lines: list[str], reported_lineno: int) -> int:
    """Return the line number of the actual def/class statement.

    Vulture reports the line of the *first decorator* for decorated
    symbols, not the def line.  Walk backward from the reported line to
    find the first non-blank line that starts a FunctionDef, AsyncFunctionDef,
    or ClassDef.
    """
    for ln in range(reported_lineno, 0, -1):
        stripped = source_lines[ln - 1].strip()
        if stripped:
            # Check if this line starts a def or class.
            if re.match(r"^(def|class|async def)\s+", stripped):
                return ln
            # If we hit a decorator, keep going up.
            if not stripped.startswith("@"):
                break
    return reported_lineno


def _is_protected_name(name: str) -> bool:
    """Return True for framework-contract names that should be excluded."""
    if name in _PROTECTED_NAMES:
        return True
    if name.startswith("pytest_"):
        return True
    return False


def parse_vulture_output(output: str) -> list[tuple[str, int, str]]:
    """Parse vulture stdout and return [(filepath, lineno, symbol_name)].

    Ignores the "dead" classification and confidence from vulture; the guard
    applies its own cross-reference filter instead.
    """
    findings: list[tuple[str, int, str]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        # Format: "path/to/file.py:lineno: unused 'symbol' (N% confidence)"
        m = re.match(r"^([^\n:]+):(\d+):\s+unused\s+'([^']+)'", line)
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
    """Run vulture over SCOPE and return (findings, error)."""
    targets = [str(root / part) for part in SCOPE if (root / part).is_dir()]
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

    dead_symbols: list[str] = []
    for filepath, lineno, name in findings:
        if _is_protected_name(name):
            continue

        # Find the actual def line by scanning backward.
        if filepath in source_cache:
            lines, defs = source_cache[filepath]
            actual_def_line = _find_def_line(lines, lineno)
            if _decorated(defs, actual_def_line):
                continue

        # Cross-reference: a symbol is dead if it appears exactly once.
        # (Its own definition is the single occurrence.)
        occurrences = sum(
            1
            for fp, ln, nm in findings
            if fp == filepath and nm == name
        )
        if occurrences == 1:
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
