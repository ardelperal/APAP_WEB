"""This script is named check_jscpd.py per the spec (REQ-QG-DRY-1) and the proposal (quality-gates-expansion). It does NOT invoke the jscpd binary — jscpd is a Node.js/Rust tool not pip-installable. This implementation is stdlib-only by construction.

The detector normalizes Python function ASTs under ``app/``, ``migration/``,
and ``scripts/`` to find Type-1/2 clones, then reports duplicated function
lines as a percentage of all scanned source lines. ``BASELINE_JSCPD_PCT`` is a
shrink-only ratchet. Tests and generated/vendor trees are outside the scan.
This extends AGENTS.md rule 25 and is enforced as script + CI step + pinning
test per rule 32.P3. Source analysis: Engram observation #24073.
"""

from __future__ import annotations

import argparse
import ast
import copy
import io
import sys
import tokenize
from collections import defaultdict
from pathlib import Path

BASELINE_JSCPD_PCT = 1.88  # measured on the PR #1 foundation tree (Python 3.14 CI runner)
SCAN_DIRS = ("app", "migration", "scripts")
MIN_CLONE_TOKENS = 50
_MIN_CLONE_GROUP_MEMBERS = 2
_PYTHON_VERSION_FLOOR = (3, 11)


class _Normalizer(ast.NodeTransformer):
    """Erase names and literal values while preserving executable structure."""

    def visit_Name(self, node: ast.Name) -> ast.AST:  # noqa: N802
        node.id = "_name"
        return self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:  # noqa: N802
        node.attr = "_attr"
        return self.generic_visit(node)

    def visit_arg(self, node: ast.arg) -> ast.AST:  # noqa: N802
        node.arg = "_arg"
        return self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> ast.AST:  # noqa: N802
        node.value = f"<{type(node.value).__name__}>"
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:  # noqa: N802
        node.name = "_function"
        node.decorator_list = []
        return self.generic_visit(node)

    def visit_AsyncFunctionDef(  # noqa: N802
        self, node: ast.AsyncFunctionDef
    ) -> ast.AST:
        node.name = "_function"
        node.decorator_list = []
        return self.generic_visit(node)


class _FunctionCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.scope: list[str] = []
        self.functions: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._visit_function(node)

    def visit_AsyncFunctionDef(  # noqa: N802
        self, node: ast.AsyncFunctionDef
    ) -> None:
        self._visit_function(node)

    def _visit_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        qualname = ".".join([*self.scope, node.name])
        self.functions.append((qualname, node))
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()


def _iter_python_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for scan_dir in SCAN_DIRS:
        base = root / scan_dir
        if not base.is_dir():
            continue
        files.extend(
            path
            for path in base.rglob("*.py")
            if "__pycache__" not in path.parts
            and not any(part in {"vendor", "generated"} for part in path.parts)
        )
    return sorted(files)


def _token_count(source: str) -> int:
    ignored = {
        tokenize.ENCODING,
        tokenize.ENDMARKER,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.NEWLINE,
        tokenize.NL,
        tokenize.COMMENT,
    }
    try:
        return sum(
            token.type not in ignored
            for token in tokenize.generate_tokens(io.StringIO(source).readline)
        )
    except (IndentationError, tokenize.TokenError):
        return 0


def _fingerprint(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    normalized = _Normalizer().visit(copy.deepcopy(node))
    ast.fix_missing_locations(normalized)
    return ast.dump(normalized, annotate_fields=True, include_attributes=False)


def measure_tree(root: Path) -> tuple[float, list[str]]:
    """Return ``(duplicate_percentage, top_region_descriptions)``."""
    clusters: dict[str, list[tuple[str, int, int]]] = defaultdict(list)
    total_lines = 0

    for path in _iter_python_files(root):
        source = path.read_text(encoding="utf-8")
        total_lines += len(source.splitlines())
        tree = ast.parse(source, filename=str(path))
        collector = _FunctionCollector()
        collector.visit(tree)
        rel = path.relative_to(root).as_posix()
        source_lines = source.splitlines()
        for qualname, node in collector.functions:
            end_line = node.end_lineno or node.lineno
            segment = "\n".join(source_lines[node.lineno - 1 : end_line])
            tokens = _token_count(segment)
            if tokens < MIN_CLONE_TOKENS:
                continue
            line_span = end_line - node.lineno + 1
            clusters[_fingerprint(node)].append(
                (f"{rel}::{qualname}", line_span, tokens)
            )

    duplicate_lines = 0
    regions: list[str] = []
    for members in clusters.values():
        if len(members) < _MIN_CLONE_GROUP_MEMBERS:
            continue
        duplicate_lines += sum(line_span for _name, line_span, _tokens in members)
        canonical = members[0]
        for duplicate in members[1:]:
            regions.append(
                f"{canonical[0]} <-> {duplicate[0]} "
                f"({min(canonical[2], duplicate[2])} tokens)"
            )

    percentage = round(duplicate_lines / total_lines * 100, 2) if total_lines else 0.0
    return percentage, sorted(regions)


def _python_version() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def check_tree(
    root: Path,
    *,
    baseline_pct: float = BASELINE_JSCPD_PCT,
) -> tuple[list[str], list[str]]:
    """Return ``(violations, notices)`` for the duplicate percentage ratchet."""
    if sys.version_info[:2] < _PYTHON_VERSION_FLOOR:
        return [
            f"check_jscpd: requires Python >= {_PYTHON_VERSION_FLOOR[0]}.{_PYTHON_VERSION_FLOOR[1]}"
        ], []
    try:
        percentage, regions = measure_tree(root)
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        return [f"cannot scan source tree ({exc})"], []

    if percentage > baseline_pct:
        details = "; ".join(regions[:5]) or "no clone regions available"
        return [
            f"duplicate code {percentage:.2f}% exceeds baseline {baseline_pct:.2f}%; "
            f"top regions: {details}"
        ], []
    if percentage < baseline_pct:
        return [], [
            f"duplicate code {percentage:.2f}% is below baseline {baseline_pct:.2f}% (Python "
            f"{_python_version()}) — lower BASELINE_JSCPD_PCT in the same PR"
        ]
    return [], []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit-baseline", action="store_true")
    parser.add_argument("root", nargs="?", type=Path)
    args = parser.parse_args(argv)
    root = (
        args.root.resolve()
        if args.root is not None
        else Path(__file__).resolve().parents[1]
    )
    if args.emit_baseline:
        percentage, regions = measure_tree(root)
        print(f"BASELINE_JSCPD_PCT = {percentage:.2f}  # measured duplicate percentage (%)")
        for region in regions[:10]:
            print(f"REGION: {region}")
        return 0

    violations, notices = check_tree(root)
    for notice in notices:
        print(f"NOTE: {notice}")
    for violation in violations:
        print(f"FAIL: {violation}")
    if violations:
        print(f"check_jscpd: {len(violations)} violation(s).")
        return 1
    percentage, _regions = measure_tree(root)
    print(
        f"check_jscpd: OK: {percentage:.2f}% <= "
        f"{BASELINE_JSCPD_PCT:.2f}% baseline"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
