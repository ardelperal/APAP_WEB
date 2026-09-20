#!/usr/bin/env python3
# HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — assets/scripts/check_layers.py
"""Hexagonal layer gate: dependency direction, vertical slicing, and layer purity.

Stdlib only, so the gate runs before the project has installed anything. Walks the AST of every
module under the root package, resolves each import to a ``(module, layer)`` pair, and fails on
any edge the architecture does not allow.

Regex cannot do this job: it breaks on line continuations, comments, aliased imports, and relative
imports. Hard Rule 9 requires the AST.

Exit codes:
    0  no violation outside BASELINE
    1  a new violation, a BASELINE entry above its recorded count, or a BASELINE entry past its
       target date while still above target
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from policy_time import add_policy_date_argument
from quality_policy import bind_envelope, expected_subjects, load_policy, subject_paths

# --------------------------------------------------------------------------------------------
# CONFIGURATION — adjust this block when instantiating. Everything below it is mechanism.
# --------------------------------------------------------------------------------------------

ROOT_PACKAGE = "app"

#: Modules every other module may depend on. Keep this set as small as it can possibly be; each
#: entry is a hole in the vertical slicing rule.
CROSS_CUTTING_MODULES = frozenset({"core"})

#: Which layers a given layer may import from. A layer absent from this table is not a layer.
ALLOWED_IMPORTS: dict[str, frozenset[str]] = {
    "domain": frozenset({"domain"}),
    "ports": frozenset({"domain", "ports"}),
    "application": frozenset({"domain", "ports", "application"}),
    "adapters": frozenset({"domain", "ports", "adapters", "shared"}),
    "shared": frozenset({"domain", "ports", "shared"}),
    "delivery": frozenset({"domain", "ports", "application", "adapters", "shared", "delivery"}),
    "di": frozenset(
        {"domain", "ports", "application", "adapters", "shared", "delivery", "di"}
    ),
}

#: Layers that must not touch a framework at all.
PURE_LAYERS = frozenset({"domain", "ports", "application"})

#: Top-level distributions banned inside PURE_LAYERS.
FORBIDDEN_IN_PURE_LAYERS = frozenset(
    {"fastapi", "sqlalchemy", "alembic", "jinja2", "httpx", "asyncpg", "starlette", "pydantic_settings"}
)

#: Paths excluded from the walk. Hard Rule 14: this is the declared untestable/ungoverned
#: boundary. Keep it thin and keep it honest — every entry here is code nobody is checking.
EXCLUDED_PARTS = frozenset({"__pycache__", ".venv", "venv", "build", "dist", "migrations"})


@dataclass(frozen=True)
class BaselineEntry:
    """A tolerated violation count with a mandatory exit plan.

    Hard Rule 12: a ratchet is a ramp toward a ceiling, never the destination. ``target`` is the
    value this key must reach; ``target_date`` is when the tolerance expires. After that date the
    gate fails even if the count never grew, which is what stops a ratchet from becoming permanent.
    """

    count: int
    target: int
    target_date: str  # ISO-8601, YYYY-MM-DD


#: Keyed by ``violation-class|source-path|import-subject``. The source line is deliberately not
#: part of the identity, so unrelated line movement does not churn the ratchet. Migrate aggregate
#: class/count baselines explicitly with ``--emit-baseline``.
BASELINE: dict[str, BaselineEntry] = {}

# --------------------------------------------------------------------------------------------
# MECHANISM
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Violation:
    key: str
    detail: str
    file: str
    line: int
    subject: str

    @property
    def identity(self) -> str:
        """Stable ratchet key, independent of line-number-only source movement."""
        return f"{self.key}|{self.file}|{self.subject}"


def _iter_source_files(root: Path) -> list[Path]:
    return subject_paths(root, load_policy())


def classify_file(path: Path, root: Path) -> tuple[str, str] | None:
    """Map a file to its ``(module, layer)``, or ``None`` when it is not layered code."""
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return None
    if len(parts) < 4 or parts[0] != ROOT_PACKAGE:
        return None
    module, layer = parts[1], parts[2]
    if layer not in ALLOWED_IMPORTS:
        return None
    return module, layer


def classify_dotted(name: str) -> tuple[str, str] | None:
    """Map a dotted import target to its ``(module, layer)``, or ``None`` when it is external."""
    parts = name.split(".")
    if len(parts) < 3 or parts[0] != ROOT_PACKAGE:
        return None
    module, layer = parts[1], parts[2]
    if layer not in ALLOWED_IMPORTS:
        return None
    return module, layer


def _absolute_target(node: ast.ImportFrom, path: Path, root: Path) -> str | None:
    """Resolve a possibly relative ``from ... import`` to an absolute dotted path."""
    if not node.level:
        return node.module
    try:
        package_parts = list(path.relative_to(root).parts[:-1])
    except ValueError:
        return None
    # level 1 is the containing package, level 2 its parent, and so on.
    upward = node.level - 1
    if upward:
        if upward > len(package_parts):
            return None
        package_parts = package_parts[:-upward]
    if node.module:
        package_parts.append(node.module)
    return ".".join(package_parts)


def _imported_names(tree: ast.AST, path: Path, root: Path) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            target = _absolute_target(node, path, root)
            if target:
                found.append((target, node.lineno))
    return found


def _check_direction(
    origin: tuple[str, str], target: tuple[str, str], imported: str, file: str, line: int
) -> Violation | None:
    _, origin_layer = origin
    _, target_layer = target
    if target_layer in ALLOWED_IMPORTS[origin_layer]:
        return None
    return Violation(
        key=f"direction:{origin_layer}->{target_layer}",
        detail=f"{origin_layer} may not import {target_layer}",
        file=file,
        line=line,
        subject=imported,
    )


def _check_slice(
    origin: tuple[str, str], target: tuple[str, str], imported: str, file: str, line: int
) -> Violation | None:
    origin_module, _ = origin
    target_module, _ = target
    if target_module == origin_module or target_module in CROSS_CUTTING_MODULES:
        return None
    return Violation(
        key=f"slice:{origin_module}->{target_module}",
        detail=f"module {origin_module} reaches across into {target_module}",
        file=file,
        line=line,
        subject=imported,
    )


def _check_purity(
    origin: tuple[str, str], imported: str, file: str, line: int
) -> Violation | None:
    _, origin_layer = origin
    if origin_layer not in PURE_LAYERS:
        return None
    distribution = imported.split(".")[0]
    if distribution not in FORBIDDEN_IN_PURE_LAYERS:
        return None
    return Violation(
        key=f"purity:{origin_layer}",
        detail=f"{origin_layer} imports framework {distribution}",
        file=file,
        line=line,
        subject=distribution,
    )


def collect_violations(root: Path) -> list[Violation]:
    violations: list[Violation] = []
    for path in _iter_source_files(root):
        display = str(path.relative_to(root)).replace("\\", "/")
        origin = classify_file(path, root)
        if origin is None:
            # Hard Rule 18: a file this gate cannot classify is a file this gate did not check.
            # Skipping it silently reports "clean" for code nobody looked at — which is how a
            # layout mismatch turns a whole codebase invisible while CI stays green. Either
            # teach classify_file the layout, or record the file in BASELINE deliberately.
            violations.append(
                Violation(
                    key="unclassified",
                    detail="not classifiable into (module, layer); this file was NOT checked",
                    file=display,
                    line=0,
                    subject="unclassified",
                )
            )
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:  # a file that cannot be parsed is a failure, not a skip
            violations.append(
                Violation(
                    key="unparseable",
                    detail=f"syntax error: {exc.msg}",
                    file=display,
                    line=exc.lineno or 0,
                    subject="syntax-error",
                )
            )
            continue
        for imported, line in _imported_names(tree, path, root):
            purity = _check_purity(origin, imported, display, line)
            if purity:
                violations.append(purity)
            target = classify_dotted(imported)
            if target is None:
                continue
            direction = _check_direction(origin, target, imported, display, line)
            if direction:
                violations.append(direction)
            slicing = _check_slice(origin, target, imported, display, line)
            if slicing:
                violations.append(slicing)
    return violations


def evaluate(violations: list[Violation], today: date) -> tuple[int, list[str]]:
    """Compare observed violations against BASELINE. Returns ``(exit_code, report_lines)``."""
    observed: dict[str, list[Violation]] = {}
    for violation in violations:
        observed.setdefault(violation.identity, []).append(violation)

    lines: list[str] = []
    failed = False

    for key in sorted(BASELINE):
        if "|" not in key:
            failed = True
            lines.append(
                f"FAIL  {key}: legacy aggregate BASELINE has no finding identities; "
                "regenerate it with --emit-baseline"
            )

    for key in sorted(observed):
        entries = observed[key]
        allowance = BASELINE.get(key)
        if allowance is None:
            failed = True
            lines.append(f"FAIL  {key}: {len(entries)} occurrence(s), not in BASELINE")
        elif len(entries) > allowance.count:
            failed = True
            lines.append(
                f"FAIL  {key}: {len(entries)} occurrence(s), BASELINE allows {allowance.count}"
            )
        elif today.isoformat() > allowance.target_date and len(entries) > allowance.target:
            failed = True
            lines.append(
                f"FAIL  {key}: BASELINE expired on {allowance.target_date} with "
                f"{len(entries)} occurrence(s), target was {allowance.target}"
            )
        elif len(entries) < allowance.count:
            lines.append(
                f"NOTE  {key}: {len(entries)} occurrence(s), below BASELINE {allowance.count}; "
                f"lower the BASELINE to lock the gain in"
            )
        for entry in entries:
            lines.append(f"        {entry.file}:{entry.line}  {entry.detail}")

    for key in sorted(BASELINE):
        if key in observed:
            continue
        lines.append(f"NOTE  {key}: no longer occurs; remove it from BASELINE")

    if not failed:
        lines.append("OK    layer gate clean")
    return (1 if failed else 0), lines


def render_baseline(violations: list[Violation], today: date, horizon_days: int = 90) -> str:
    """Emit the explicit migration from aggregate classes to stable finding identities."""
    target_date = date.fromordinal(today.toordinal() + horizon_days).isoformat()
    observed: dict[str, int] = {}
    for violation in violations:
        observed[violation.identity] = observed.get(violation.identity, 0) + 1
    lines = ["BASELINE: dict[str, BaselineEntry] = {"]
    for identity in sorted(observed):
        lines.append(
            f'    "{identity}": BaselineEntry(count={observed[identity]}, '
            f'target=0, target_date="{target_date}"),'
        )
    lines.append("}")
    return "\n".join(lines)


def build_report(root: Path, violations: list[Violation], status: str, policy_date: date, files_seen: int = 0) -> dict:
    unclassified = sum(1 for violation in violations if violation.key == "unclassified")
    report = {
        "gate": "layers",
        "policy_date": policy_date.isoformat(),
        "status": status,
        "indicators": {
            "violations": len(violations),
            "violation_classes": len({violation.key for violation in violations}),
            # Coverage of the gate itself: how much of the package it actually inspected.
            "files_checked": files_seen - unclassified,
            "files_unclassified": unclassified,
        },
        "ceilings": {"violations": 0, "violation_classes": 0, "files_unclassified": 0},
        "findings": [
            {"file": violation.file, "line": violation.line, "detail": violation.detail}
            for violation in sorted(violations, key=lambda item: (item.file, item.line, item.key))
        ],
    }
    unclassified_subjects = sorted(
        {violation.file for violation in violations if violation.key in {"unclassified", "syntax-error"}}
    )
    checked = [path for path in expected_subjects(root) if path not in unclassified_subjects]
    return bind_envelope(
        report,
        root,
        "layers",
        checked=checked,
        unclassified=unclassified_subjects,
    )


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
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="repository root containing the package directory (default: cwd)",
    )
    parser.add_argument("--json", action="store_true", help="emit the indicator envelope")
    parser.add_argument(
        "--emit-baseline",
        action="store_true",
        help="emit a stable-identity BASELINE for explicit migration",
    )
    args = parser.parse_args(argv)

    root = args.root.resolve()
    if not (root / ROOT_PACKAGE).is_dir():
        message = f"root package '{ROOT_PACKAGE}' not found under {root}"
        if args.json:
            report = build_report(root, [], "error", args.policy_date, 0)
            report["detail"] = message
            print(json.dumps(report))
        else:
            print(f"FAIL  {message}", file=sys.stderr)
        return 1

    files_seen = len(_iter_source_files(root))
    if files_seen == 0:
        message = f"no eligible Python files found under {root / ROOT_PACKAGE}"
        if args.json:
            report = build_report(root, [], "error", args.policy_date, files_seen)
            report["detail"] = message
            print(json.dumps(report, indent=2))
        else:
            print(f"FAIL  {message}", file=sys.stderr)
        return 1

    violations = collect_violations(root)
    if args.emit_baseline:
        print(render_baseline(violations, args.policy_date))
        return 0
    exit_code, lines = evaluate(violations, args.policy_date)

    if args.json:
        status = "pass" if exit_code == 0 else "fail"
        print(json.dumps(build_report(root, violations, status, args.policy_date, files_seen), indent=2))
    else:
        for line in lines:
            print(line)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
