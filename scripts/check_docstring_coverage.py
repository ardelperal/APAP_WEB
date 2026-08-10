"""Docstring coverage ratchet for APAP_WEB (issue #339).

Enforces that docstring coverage in ``app/``, ``migration/``, and
``scripts/`` does not fall below the ``BASELINE_COVERAGE_FLOOR``.
Coverage is measured as the ratio of definition nodes that carry a
docstring (not empty-string) to the total count of definition nodes.

Scope: ``app/`` + ``migration/`` + ``scripts/``.
Tests/ is intentionally excluded.

Definition types tracked separately:
  - Module-level (the file's own docstring)
  - ClassDef
  - FunctionDef / AsyncFunctionDef

Usage::

    python scripts/check_docstring_coverage.py [root]

``root`` defaults to the repository root. Exit code 0 when coverage is
at or above the floor; 1 when coverage has dropped below it.

Stdlib-only, deterministic. CI runs this in the ``lint`` job.

Tests: ``tests/test_docstring_coverage.py``.
"""

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

# ── Tunables ────────────────────────────────────────────────────────────────

# Directories subject to the coverage check.
SCAN_DIRS = ("app", "migration", "scripts")

# Ratchet floor: coverage (%) must not drop below this value.
# Measured 2026-07-31 on main (837d6cf) — do NOT lower this value.
# If you improve coverage, update this constant in the same PR that
# added the docstrings.
BASELINE_COVERAGE_FLOOR = 73.0


# ── Data model ──────────────────────────────────────────────────────────────

@dataclass
class DocstringStats:
    total: int = 0
    documented: int = 0

    @property
    def coverage(self) -> float:
        if self.total == 0:
            return 100.0
        return round(self.documented / self.total * 100, 2)

    def is_acceptable(self, floor: float) -> bool:
        return self.coverage >= floor


# ── Core logic ───────────────────────────────────────────────────────────────

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
        )
    return sorted(files)


def _has_docstring(node: ast.AST) -> bool:
    """Return True iff ``node`` carries a non-empty docstring."""
    doc = ast.get_docstring(node)
    return doc is not None and doc.strip() != ""


def measure_docstrings(root: Path) -> tuple[DocstringStats, DocstringStats, DocstringStats]:
    """Return (module_stats, class_stats, function_stats) for all scanned files.

    Only top-level definitions are counted (nested ones are excluded)
    because docstrings on inner functions are stylistic; the ratchet
    tracks the public API surface.
    """
    module_stats = DocstringStats()
    class_stats = DocstringStats()
    function_stats = DocstringStats()

    for path in _iter_python_files(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue

        # Module docstring
        module_stats.total += 1
        if _has_docstring(tree):
            module_stats.documented += 1

        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                class_stats.total += 1
                if _has_docstring(node):
                    class_stats.documented += 1
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                function_stats.total += 1
                if _has_docstring(node):
                    function_stats.documented += 1

    return module_stats, class_stats, function_stats


def measure_total_coverage(
    root: Path,
) -> DocstringStats:
    """Return a single combined DocstringStats across all three definition types."""
    mod, cls, fn = measure_docstrings(root)
    return DocstringStats(
        total=mod.total + cls.total + fn.total,
        documented=mod.documented + cls.documented + fn.documented,
    )


# ── CLI ─────────────────────────────────────────────────────────────────────

def _pin_output_encoding() -> None:
    """Pin stdout/stderr to UTF-8: output must not depend on the locale (issue #488)."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _pin_output_encoding()
    args = sys.argv[1:] if argv is None else argv
    root = Path(args[0]).resolve() if args else Path(__file__).resolve().parents[1]

    total_stats = measure_total_coverage(root)
    mod_stats, cls_stats, fn_stats = measure_docstrings(root)

    coverage = total_stats.coverage
    floor = BASELINE_COVERAGE_FLOOR

    print(f"Docstring coverage: {coverage:.2f}%  (floor: {floor:.1f}%)")
    print(f"  Modules:  {mod_stats.documented}/{mod_stats.total}  ({mod_stats.coverage:.1f}%)")
    print(f"  Classes:  {cls_stats.documented}/{cls_stats.total}  ({cls_stats.coverage:.1f}%)")
    print(f"  Funcs:    {fn_stats.documented}/{fn_stats.total}  ({fn_stats.coverage:.1f}%)")

    if coverage < floor:
        print(
            f"\nFAIL: coverage {coverage:.2f}% is below floor {floor:.1f}%. "
            f"Add docstrings to raise it, then update BASELINE_COVERAGE_FLOOR "
            f"in scripts/check_docstring_coverage.py to lock in the improvement.",
            file=sys.stderr,
        )
        return 1

    print(f"\nOK: coverage {coverage:.2f}% is at or above floor {floor:.1f}%.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
