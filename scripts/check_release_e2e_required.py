"""Decide whether a deployed range requires the authenticated e2e battery (issue #1131).

The release gate only needs the expensive authenticated production e2e when the
range touches an e2e-sensitive surface (authentication, session, CSRF, settings,
migrations, the e2e mock login, deploy configuration). The sensitive surface is
versioned data in ``.github/release-e2e-paths.txt``.

Pattern file format: one glob per line; ``#`` starts a comment line; blank lines
are ignored. Globs are matched against repository-relative POSIX paths, anchored
at both ends:

    ``*``   any characters except ``/``
    ``?``   exactly one character except ``/``
    ``**``  any characters including ``/`` (``a/**/b`` also matches ``a/b``)

Usage::

    python scripts/check_release_e2e_required.py --base BASE_SHA --head HEAD_SHA
    git diff --name-only A..B | python scripts/check_release_e2e_required.py --stdin

Exit codes:
    0  - not required: no changed file matches a sensitive pattern
    10 - required: a sensitive file changed, or the decision could not be made
         (fail closed: an unreadable/empty pattern file or a git failure)
    2  - usage error

Tests: ``tests/test_check_release_e2e_required.py``.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

DEFAULT_PATTERNS = Path(__file__).resolve().parents[1] / ".github" / "release-e2e-paths.txt"
EXIT_NOT_REQUIRED = 0
EXIT_REQUIRED = 10
EXIT_USAGE_ERROR = 2


class SelectorError(Exception):
    """The decision could not be made; callers must treat the battery as required."""


def load_patterns(path: Path) -> list[str]:
    """Read the glob list; an unreadable or empty file is an error, never a pass."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        message = f"cannot read pattern file {path}: {error}"
        raise SelectorError(message) from error
    patterns = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not patterns:
        message = f"pattern file {path} holds no patterns"
        raise SelectorError(message)
    return patterns


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    parts: list[str] = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            parts.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("**", index):
            parts.append(".*")
            index += 2
        elif pattern[index] == "*":
            parts.append("[^/]*")
            index += 1
        elif pattern[index] == "?":
            parts.append("[^/]")
            index += 1
        else:
            parts.append(re.escape(pattern[index]))
            index += 1
    return re.compile("".join(parts))


def matches(pattern: str, path: str) -> bool:
    """True when the whole ``path`` matches ``pattern`` (semantics in the module docstring)."""
    return _glob_to_regex(pattern).fullmatch(path) is not None


def matching_files(files: Iterable[str], patterns: Sequence[str]) -> list[str]:
    """Return the sorted, de-duplicated files matched by at least one pattern."""
    compiled = [_glob_to_regex(pattern) for pattern in patterns]
    return sorted({f for f in files if any(rx.fullmatch(f) for rx in compiled)})


def changed_files_from_git(base: str, head: str, cwd: Path | None = None) -> list[str]:
    """List files changed between ``base`` and ``head`` (renames report both paths)."""
    for ref in (base, head):
        if not ref or ref.startswith("-"):
            message = f"refusing suspicious git ref {ref!r}"
            raise SelectorError(message)
    argv = ["git", "diff", "--name-only", "--no-renames", "-z", f"{base}..{head}"]
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            argv, check=True, capture_output=True, cwd=cwd
        )
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", b"") or b""
        reason = detail.decode("utf-8", "replace").strip() or str(error)
        message = f"git diff {base}..{head} failed: {reason}"
        raise SelectorError(message) from error
    return [name for name in result.stdout.decode("utf-8").split("\0") if name]


def _pin_output_encoding() -> None:
    """Pin stdout/stderr to UTF-8: output must not depend on the locale (issue #488)."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", help="base revision of the deployed range")
    parser.add_argument("--head", help="head revision of the deployed range")
    parser.add_argument("--stdin", action="store_true", help="read changed files from stdin")
    parser.add_argument(
        "--patterns", type=Path, default=DEFAULT_PATTERNS, help="sensitive-path glob file"
    )
    return parser


def _parse(argv: list[str] | None) -> argparse.Namespace | None:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return None
    has_range = args.base is not None and args.head is not None
    half_range = (args.base is None) != (args.head is None)
    if half_range or args.stdin == has_range:
        return None
    return args


def main(argv: list[str] | None = None) -> int:
    """Print the decision and return the exit code documented in the module docstring."""
    _pin_output_encoding()
    args = _parse(argv)
    if args is None:
        print("::error::usage: pass either --base and --head, or --stdin")
        return EXIT_USAGE_ERROR
    try:
        patterns = load_patterns(args.patterns)
        files = (
            [line.strip() for line in sys.stdin.read().splitlines() if line.strip()]
            if args.stdin
            else changed_files_from_git(args.base, args.head)
        )
    except SelectorError as error:
        print(f"::notice::e2e required: cannot decide, failing closed ({error})")
        return EXIT_REQUIRED

    hits = matching_files(files, patterns)
    if hits:
        print(f"::notice::e2e required: {len(hits)} sensitive file(s) changed: {', '.join(hits)}")
        return EXIT_REQUIRED
    print(f"::notice::e2e not required: none of {len(files)} changed file(s) is sensitive")
    return EXIT_NOT_REQUIRED


if __name__ == "__main__":
    raise SystemExit(main())
