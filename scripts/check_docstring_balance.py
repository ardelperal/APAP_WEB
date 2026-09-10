#!/usr/bin/env python3
"""Detect files where a triple-quoted string opens but never closes.

Invocation (Makefile / CI):
    python scripts/check_docstring_balance.py <file_or_dir> ...

Invocation (pre-commit, files piped on stdin):
    python scripts/check_docstring_balance.py --stdin

The guard catches the failure mode where a class or module docstring
starts with a triple-quoted opener but the matching triple-quoted
closer is missing: Python compiles the file (the rest of the body
becomes a string literal) and py_compile succeeds, but at import time
the class body is empty and its methods raise NameError at runtime.
The bug silently propagates through a merge and is invisible to ruff / mypy.

Only SyntaxError instances whose message mentions "triple-quoted",
"unterminated" or "unclosed string" are reported; other syntax errors
(e.g. missing colon, invalid token) are left to ruff.

Exit codes
----------
0   — no unbalanced docstrings found
1   — one or more files have unbalanced docstrings
2   — invocation error (wrong arguments)
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path


# Error-message fragments that indicate an unclosed triple-quoted string.
# Covers both CPython 3.x and the python-compile stdlib error messages.
_UNBALANCED_FRAGMENTS = (
    "unterminated triple-quoted string",
    "EOF in multi-line string",
    "unclosed string",
    "unclosed string literal",
)


def is_unbalanced_docstring(exc: SyntaxError) -> bool:
    msg = exc.msg.lower()
    return any(frag.lower() in msg for frag in _UNBALANCED_FRAGMENTS)


def check_file(path: Path) -> list[str]:
    """Return list of error lines for *path*, or empty list if clean."""
    errors: list[str] = []
    try:
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        ast.parse(src, filename=str(path))
    except SyntaxError as exc:
        if is_unbalanced_docstring(exc):
            lineno = exc.lineno
            line_text = ""
            if lineno is not None:
                src_lines = src.splitlines()
                if 0 < lineno <= len(src_lines):
                    line_text = src_lines[lineno - 1].strip()
            msg = f"{path}:{lineno or '?'}: {exc.msg}"
            if line_text:
                msg += f"  -> {line_text!r}"
            errors.append(msg)
    return errors


def paths_from_args(args: list[str]) -> list[Path]:
    """Resolve CLI positional arguments to a list of file Path objects."""
    roots: list[Path] = []
    for arg in args:
        p = Path(arg)
        if not p.exists():
            print(f"check_docstring_balance: {arg}: No such file or directory", file=sys.stderr)
            sys.exit(2)
        if p.is_dir():
            roots.extend(p.rglob("*.py"))
        else:
            roots.append(p)
    return roots


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--stdin":
        # pre-commit: files are listed one per line on stdin
        file_paths = [Path(line.strip()) for line in sys.stdin if line.strip()]
    else:
        if len(sys.argv) < 2:
            print(f"Usage: {sys.argv[0]} [--stdin] <file-or-dir>...", file=sys.stderr)
            sys.exit(2)
        file_paths = paths_from_args(sys.argv[1:])

    all_errors: list[str] = []
    for path in sorted(file_paths):
        if path.is_file():
            all_errors.extend(check_file(path))

    if all_errors:
        print("check_docstring_balance: unbalanced triple-quoted strings found:")
        for err in all_errors:
            print("  " + err)
        sys.exit(1)

    if len(sys.argv) < 2 or sys.argv[1] != "--stdin":
        print(f"check_docstring_balance: clean ({len(file_paths)} files scanned)")


if __name__ == "__main__":
    main()
