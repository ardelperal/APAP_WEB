#!/usr/bin/env python3
# HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — assets/scripts/check_dry.py
"""DRY gate — type-1 and type-2 duplicate block detection over the AST.

Text-based clone detection reports formatting as duplication and misses everything that was
copy-pasted and then renamed. This works on normalised syntax trees instead: identifier names and
literal values are replaced with positional placeholders, so a block that was copied and had its
variables renamed still matches, while two blocks that merely look alike do not.

Attribute and function names are deliberately NOT normalised. That makes the detector
conservative: it reports fewer clones than a maximally aggressive normaliser would. For a gate
that is the right bias — a DRY gate that cries wolf gets switched off within a month, and a gate
that is switched off protects nothing.

DETERMINISM: hashing uses ``hashlib.sha256`` over a canonical dump, never the builtin ``hash()``,
which is salted per process by ``PYTHONHASHSEED`` and would make this gate report different
results on identical code from one run to the next.

Exit codes:
    0  no duplicate block outside BASELINE
    1  a new duplicate group, a BASELINE entry that grew, or a BASELINE entry past its target date
"""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from policy_time import add_policy_date_argument
from quality_policy import bind_envelope, expected_subjects, load_policy, subject_paths

# --------------------------------------------------------------------------------------------
# CONFIGURATION
# --------------------------------------------------------------------------------------------

ROOT_PACKAGE = "app"

#: Consecutive statements that must match before a block counts as duplication. Lower is
#: stricter and noisier; 5 is the point where a match stops being a coincidence.
MIN_STATEMENTS = 5

#: How many places a block must appear in to count. Two is duplication; the rule of three is a
#: refactoring heuristic, not a gate.
MIN_OCCURRENCES = 2

EXCLUDED_PARTS = frozenset({"__pycache__", ".venv", "venv", "build", "dist", "migrations"})


@dataclass(frozen=True)
class BaselineEntry:
    """A tolerated duplicate group with a mandatory exit plan (Hard Rule 12)."""

    occurrences: int
    target: int
    target_date: str  # ISO-8601, YYYY-MM-DD


#: Keyed by the clone's own digest (``dup:<12 hex>``). Shrink-only.
#:
#: The key deliberately does NOT include the file list. An earlier version joined the paths of
#: every file in the group, which made the key change the moment the same block was copied into
#: one more file — so the BASELINE entry stopped matching and the ratchet read a grown clone as
#: a brand-new one. A ratchet whose key moves with the thing it is ratcheting is not a ratchet.
#: The digest changes only when the duplicated code itself changes structurally, which is
#: precisely when the entry should be re-reviewed.
BASELINE: dict[str, BaselineEntry] = {}

# --------------------------------------------------------------------------------------------
# MECHANISM
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Occurrence:
    file: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class CloneGroup:
    key: str
    digest: str
    statements: int
    occurrences: tuple[Occurrence, ...]


class _Normaliser(ast.NodeTransformer):
    """Rewrite identifiers and literals to positional placeholders (type-2 normalisation)."""

    def __init__(self) -> None:
        self._names: dict[str, str] = {}

    def _placeholder(self, name: str) -> str:
        if name not in self._names:
            self._names[name] = f"V{len(self._names)}"
        return self._names[name]

    def visit_Name(self, node: ast.Name) -> ast.AST:  # noqa: N802 - ast API
        node.id = self._placeholder(node.id)
        return self.generic_visit(node)

    def visit_arg(self, node: ast.arg) -> ast.AST:
        node.arg = self._placeholder(node.arg)
        node.annotation = None
        return self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> ast.AST:  # noqa: N802 - ast API
        node.value = type(node.value).__name__
        node.kind = None
        return node


def _digest(statements: list[ast.stmt]) -> str:
    module = ast.Module(body=copy.deepcopy(statements), type_ignores=[])
    normalised = _Normaliser().visit(module)
    canonical = ast.dump(normalised, annotate_fields=False, include_attributes=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _statement_bodies(tree: ast.AST):
    """Yield every list of consecutive statements in the tree."""
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            body = getattr(node, field, None)
            if isinstance(body, list) and len(body) >= MIN_STATEMENTS:
                if all(isinstance(item, ast.stmt) for item in body):
                    yield body


def collect_groups(root: Path) -> list[CloneGroup]:
    buckets: dict[str, list[tuple[Occurrence, int]]] = {}
    for path in subject_paths(root, load_policy()):
        display = str(path.relative_to(root)).replace("\\", "/")
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue  # check_layers.py owns the unparseable-file failure
        for body in _statement_bodies(tree):
            for start in range(len(body) - MIN_STATEMENTS + 1):
                window = body[start : start + MIN_STATEMENTS]
                occurrence = Occurrence(
                    file=display,
                    start_line=window[0].lineno,
                    end_line=getattr(window[-1], "end_lineno", window[-1].lineno),
                )
                buckets.setdefault(_digest(window), []).append((occurrence, MIN_STATEMENTS))

    # Stable ordering: most occurrences first, then digest. Never rely on dict insertion order
    # for a verdict.
    ordered = sorted(buckets.items(), key=lambda item: (-len(item[1]), item[0]))

    groups: list[CloneGroup] = []
    claimed: set[tuple[str, int]] = set()

    def _overlaps(occurrence: Occurrence) -> bool:
        return any(
            (occurrence.file, line) in claimed
            for line in range(occurrence.start_line, occurrence.end_line + 1)
        )

    def _claim(occurrence: Occurrence) -> None:
        for line in range(occurrence.start_line, occurrence.end_line + 1):
            claimed.add((occurrence.file, line))

    for digest, entries in ordered:
        if len(entries) < MIN_OCCURRENCES:
            continue
        # Accept greedily in a stable order, claiming as we go. Claiming INSIDE the loop is what
        # collapses a long clone region into one finding: a sliding window over the same region
        # produces one occurrence per offset, and without this the gate reports the same
        # duplication dozens of times. A gate that reports 333 findings for 37 real clones gets
        # switched off inside a week, and a gate that is switched off protects nothing.
        fresh: list[Occurrence] = []
        for occurrence, _ in sorted(
            entries, key=lambda item: (item[0].file, item[0].start_line)
        ):
            if _overlaps(occurrence):
                continue
            fresh.append(occurrence)
            _claim(occurrence)
        if len(fresh) < MIN_OCCURRENCES:
            # Fewer than two distinct places left once overlaps are removed: this was part of a
            # region already reported, not a clone of its own. Release nothing — the lines stay
            # claimed by whoever reported them.
            continue
        groups.append(
            CloneGroup(
                key=f"dup:{digest[:12]}",
                digest=digest[:12],
                statements=MIN_STATEMENTS,
                occurrences=tuple(fresh),
            )
        )
    return sorted(groups, key=lambda group: group.key)


def _duplicated_statement_total(groups: list[CloneGroup]) -> int:
    return sum(group.statements * len(group.occurrences) for group in groups)


def _total_statements(root: Path) -> int:
    total = 0
    for path in subject_paths(root, load_policy()):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        total += sum(1 for node in ast.walk(tree) if isinstance(node, ast.stmt))
    return total


def evaluate(groups: list[CloneGroup], today: date) -> tuple[int, list[str]]:
    lines: list[str] = []
    failed = False
    observed: dict[str, list[CloneGroup]] = {}
    for group in groups:
        observed.setdefault(group.key, []).append(group)

    for key in sorted(observed):
        found = observed[key]
        count = sum(len(group.occurrences) for group in found)
        allowance = BASELINE.get(key)
        if allowance is None:
            failed = True
            lines.append(f"FAIL  {key}: {count} duplicated block(s), not in BASELINE")
        elif count > allowance.occurrences:
            failed = True
            lines.append(
                f"FAIL  {key}: {count} duplicated block(s), BASELINE allows {allowance.occurrences}"
            )
        elif today.isoformat() > allowance.target_date and count > allowance.target:
            failed = True
            lines.append(
                f"FAIL  {key}: BASELINE expired on {allowance.target_date} with {count} "
                f"duplicated block(s), target was {allowance.target}"
            )
        elif count < allowance.occurrences:
            lines.append(
                f"NOTE  {key}: down to {count} block(s); lower the BASELINE to lock the gain in"
            )
        for group in found:
            for occurrence in group.occurrences:
                lines.append(
                    f"        {occurrence.file}:{occurrence.start_line}-{occurrence.end_line}  "
                    f"[{group.digest}] {group.statements} statements"
                )

    for key in sorted(BASELINE):
        if key not in observed:
            lines.append(f"NOTE  {key}: no longer duplicated; remove it from BASELINE")

    if not failed:
        lines.append(f"OK    no duplicated block of {MIN_STATEMENTS}+ statements")
    return (1 if failed else 0), lines


def build_report(root: Path, groups: list[CloneGroup], status: str, policy_date: date) -> dict:
    duplicated = _duplicated_statement_total(groups)
    total = _total_statements(root)
    report = {
        "gate": "dry",
        "policy_date": policy_date.isoformat(),
        "status": status,
        "indicators": {
            "duplicate_groups": len(groups),
            "duplicated_statements": duplicated,
            "duplicated_ratio_pct": round(100 * duplicated / total, 2) if total else 0.0,
            "statements_measured": total,
        },
        "ceilings": {"duplicate_groups": 0},
        "findings": [
            {
                "file": occurrence.file,
                "line": occurrence.start_line,
                "detail": f"duplicated block [{group.digest}] "
                f"{occurrence.start_line}-{occurrence.end_line}",
            }
            for group in groups
            for occurrence in group.occurrences
        ],
    }
    unclassified: list[str] = []
    for path in subject_paths(root, load_policy()):
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            unclassified.append(path.relative_to(root).as_posix())
    checked = [path for path in expected_subjects(root) if path not in unclassified]
    return bind_envelope(report, root, "dry", checked=checked, unclassified=unclassified)


def _pin_output_encoding() -> None:
    """Pin stdout/stderr to UTF-8.

    Python picks the output encoding from the platform locale, so the same gate emits different
    bytes on a Windows workstation (cp1252) and a Linux runner (utf-8) — and a non-encodable
    character crashes the write outright. A harness that claims determinism cannot let its own
    output depend on where it ran.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _pin_output_encoding()
    parser = argparse.ArgumentParser(description=__doc__)
    add_policy_date_argument(parser)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    parser.add_argument("--json", action="store_true", help="emit the indicator envelope")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    if not (root / ROOT_PACKAGE).is_dir():
        message = f"root package '{ROOT_PACKAGE}' not found under {root}"
        if args.json:
            report = build_report(root, [], "error", args.policy_date)
            report["detail"] = message
            print(json.dumps(report))
        else:
            print(f"FAIL  {message}", file=sys.stderr)
        return 1

    groups = collect_groups(root)
    if _total_statements(root) == 0:
        message = f"no eligible statements found under {root / ROOT_PACKAGE}"
        if args.json:
            report = build_report(root, groups, "error", args.policy_date)
            report["detail"] = message
            print(json.dumps(report, indent=2))
        else:
            print(f"FAIL  {message}", file=sys.stderr)
        return 1

    exit_code, lines = evaluate(groups, args.policy_date)

    if args.json:
        print(json.dumps(build_report(root, groups, "pass" if exit_code == 0 else "fail", args.policy_date), indent=2))
    else:
        for line in lines:
            print(line)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
