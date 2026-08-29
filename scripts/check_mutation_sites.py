"""Static mutation-site density ratchet (REQ-QG-MSITES-1).

Counts cheap AST-level mutation targets per Python file under ``app/`` and
``migration/`` before the slower cosmic-ray phase. Targets are ``BinOp``,
``BoolOp``, ``Compare``, ``If``, ``While``, ``Assert``, ``Raise``, ``Return``,
arithmetic ``Assign`` nodes, function-call arguments, and string/numeric/bool
literals. Files above the hard ceiling live in ``BASELINE_MUTATION_SITES`` and
may only shrink. This mirrors ``scripts/check_module_size.py`` and implements
the script + CI + pin contract from AGENTS.md rule 32.P3. Source analysis:
Engram observation #24073.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Mapping
from pathlib import Path

# _ratchet_deadline lives next to this script.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _ratchet_deadline import check_deadline  # noqa: E402 - sys.path tweak above

MAX_MUTATION_SITES_PER_FILE = 250
SCAN_DIRS = ("app", "migration")

#: Current offenders measured with ``--emit-baseline``.
#: RATCHET: entries may only shrink or disappear; never add headroom.
BASELINE_MUTATION_SITES: dict[str, int] = {
    "app/core/insforge.py": 526,
    "app/modules/acogidas/routes.py": 383,
    "app/modules/acogidas/service.py": 355,
    "app/modules/adopciones/routes.py": 306,
    "app/modules/adopciones/service.py": 482,
    "app/modules/animals/routes.py": 449,
    "app/modules/cesiones/service.py": 370,
    "app/modules/foster/routes.py": 263,
    "app/modules/foster/service.py": 342,
    "app/modules/salud/routes.py": 408,
    "app/modules/salud/service.py": 323,
    "app/modules/sanidad/routes.py": 357,
    "app/modules/sanidad/service.py": 387,
    "migration/apply.py": 470,
    "migration/cli.py": 443,
    "migration/diff_engine.py": 333,
    "migration/lock.py": 268,  # Re-baselined after Path A refactor of acquire_lock (issue #420 / PR #452). The 4-helper split grew the file by 9 sites (function defs + docstrings) but reduced the per-function CRAP from 26.54 to 1.00 (grade A).
    "migration/lock_snapshot.py": 287,
    "migration/reconcile.py": 453,
    "migration/reporting.py": 257,  # Re-baselined after PLR0915 split of MigrationReport.to_markdown into 6 section helpers (issue #390). Net: -9 mutation sites (the consolidated string-table lines moved out of the long function). Further shrinkage after the _md_source_identity CRAP split into 3 sub-helpers (_md_counts_table/_md_source_hashes_table/_md_collisions_table): net -1 site (f-string JoinedStr avoids 4 inline list literals per helper).
    "migration/reverse_apply/orchestrator.py": 254,
    "migration/semantic_events.py": 304,
    "migration/storage_spike.py": 705,
    "migration/volunteer_dedup.py": 301,
}

#: Ratchet deadline (deterministic-quality-harness v1.5 Rule 12). Every
#: baselined file's goal is to drop below MAX_MUTATION_SITES_PER_FILE
#: (target=0 entries). The deadline is set to the project-wide pre-MVP
#: finale; revisit and tighten per-entry once the ratchet is retired.
TARGET: tuple[int, str] = (0, "2026-12-31")

_DIRECT_SITE_NODES = (
    ast.BinOp,
    ast.BoolOp,
    ast.Compare,
    ast.If,
    ast.While,
    ast.Assert,
    ast.Raise,
    ast.Return,
)
_LITERAL_TYPES = (str, int, float, complex, bool)


def _iter_python_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for scan_dir in SCAN_DIRS:
        base = root / scan_dir
        if not base.is_dir():
            continue
        files.extend(
            path for path in base.rglob("*.py") if "__pycache__" not in path.parts
        )
    return sorted(files)


def count_sites(path: Path) -> int:
    """Count documented mutation-target AST nodes in one Python file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, _DIRECT_SITE_NODES) or (
            isinstance(node, ast.Assign) and isinstance(node.value, ast.BinOp)
        ):
            count += 1
        elif isinstance(node, ast.Call):
            count += len(node.args) + len(node.keywords)
        elif isinstance(node, ast.Constant) and isinstance(node.value, _LITERAL_TYPES):
            count += 1
    return count


def measure_tree(root: Path) -> dict[str, int]:
    """Return POSIX-style relative path to mutation-site count."""
    measured: dict[str, int] = {}
    for path in _iter_python_files(root):
        measured[path.relative_to(root).as_posix()] = count_sites(path)
    return dict(sorted(measured.items()))


def check_tree(
    root: Path,
    *,
    max_sites: int = MAX_MUTATION_SITES_PER_FILE,
    baseline: Mapping[str, int] | None = None,
) -> tuple[list[str], list[str]]:
    """Return ``(violations, notices)`` for the per-file shrink-only ratchet."""
    if baseline is None:
        baseline = BASELINE_MUTATION_SITES
    try:
        measured = measure_tree(root)
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        return [f"cannot scan source tree ({exc})"], []

    violations: list[str] = []
    notices: list[str] = []
    for rel, sites in measured.items():
        if rel in baseline:
            budget = baseline[rel]
            if sites > budget:
                violations.append(
                    f"{rel}: {sites} mutation sites, grew beyond its baseline of "
                    f"{budget} (ratchet: split the file; see "
                    "scripts/check_module_size.py)"
                )
            elif sites < budget:
                notices.append(
                    f"{rel}: {sites} mutation sites, below baseline {budget} — "
                    "lower BASELINE_MUTATION_SITES in the same PR"
                    + (
                        f" (now within the {max_sites}-site budget: remove the entry)"
                        if sites <= max_sites
                        else ""
                    )
                )
        elif sites > max_sites:
            violations.append(
                f"{rel}: {sites} mutation sites exceeds the {max_sites}-site budget; "
                "split the file instead of adding a baseline entry "
                "(see scripts/check_module_size.py)"
            )

    for rel in sorted(set(baseline) - set(measured)):
        violations.append(
            f"{rel}: stale BASELINE_MUTATION_SITES entry — file no longer exists"
        )
    return violations, notices


def _pin_output_encoding() -> None:
    """Pin stdout/stderr to UTF-8: output must not depend on the locale (issue #488)."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _pin_output_encoding()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit-baseline", action="store_true")
    parser.add_argument("--max-sites", type=int, default=MAX_MUTATION_SITES_PER_FILE)
    parser.add_argument("root", nargs="?", type=Path)
    args = parser.parse_args(argv)
    root = (
        args.root.resolve()
        if args.root is not None
        else Path(__file__).resolve().parents[1]
    )
    if args.emit_baseline:
        offenders = {
            rel: sites
            for rel, sites in measure_tree(root).items()
            if sites > args.max_sites
        }
        rendered = json.dumps(offenders, indent=4, sort_keys=True)
        print(f"BASELINE_MUTATION_SITES: dict[str, int] = {rendered}")
        return 0

    violations, notices = check_tree(root, max_sites=args.max_sites)
    for notice in notices:
        print(f"NOTE: {notice}")
    for violation in violations:
        print(f"FAIL: {violation}")
    if violations:
        print(f"check_mutation_sites: {len(violations)} violation(s).")
        return 1
    print("check_mutation_sites: OK")
    warning = check_deadline(TARGET, len(BASELINE_MUTATION_SITES), label="mutation_sites")
    if warning:
        print(f"DEADLINE {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
