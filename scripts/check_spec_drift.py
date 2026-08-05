"""Spec-drift detector: flags unchecked tasks.md tasks that describe creating
code that already exists.

Per issue #335, the mechanically-checkable subset: unchecked tasks that use
creation-intent language (Create/Añadir/Add/Implement/etc.) followed by a
backtick reference to something that already exists in the codebase.

This catches the pattern where a checkbox was not ticked when the code landed.

Stdlib-only: pathlib, re.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Datatypes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Checkbox:
    line: int
    checked: bool
    text: str  # full checkbox body


@dataclass(frozen=True)
class TasksFile:
    path: Path
    checkboxes: list[Checkbox]


@dataclass(frozen=True)
class Drift:
    file: Path
    line: int
    kind: str  # "unchecked_creation_exists"
    reference: str
    message: str


# ---------------------------------------------------------------------------
# Markdown parsing
# ---------------------------------------------------------------------------

# Matches: "- [x] ..." or "- [ ] ..."
_CHECKBOX_RE = re.compile(r"^(\s*)-\s*\[([ xX])\]\s*(.*)$")
# Backtick-quoted code references
_BACKTICK_REF_RE = re.compile(r"`([^`]+)`")
# Creation-intent words (with possible task-ID prefix like **T-6.1**: before them)
_CREATION_INTENT_RE = re.compile(
    r"(?:^\s*\*\*[\w.-]+\*\*:?\s*)?"
    r"(?:Create|Añadir|Add|Implement|Wire|Extract|Build)"
    r"\b",
    re.IGNORECASE,
)


def _parse_checkbox_line(line_no: int, text: str) -> Checkbox | None:
    m = _CHECKBOX_RE.match(text)
    if not m:
        return None
    checked = m.group(2).lower() == "x"
    body = m.group(3).strip()
    return Checkbox(line=line_no, checked=checked, text=body)


def scan_tasks_md(tasks_path: Path) -> TasksFile:
    content = tasks_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    checkboxes = [
        _parse_checkbox_line(i, line)
        for i, line in enumerate(lines, start=1)
    ]
    return TasksFile(
        path=tasks_path,
        checkboxes=[cb for cb in checkboxes if cb is not None],
    )


# ---------------------------------------------------------------------------
# Code-existence checks
# ---------------------------------------------------------------------------

def _file_exists(repo_root: Path, ref: str) -> bool:
    # Strip leading ./ or / used in task descriptions
    path = ref[2:] if ref.startswith(("./", ".\\")) else ref.lstrip("/\\")
    return (repo_root / path).is_file()


# ---------------------------------------------------------------------------
# Core detection
# ---------------------------------------------------------------------------

# Only check file paths (not symbol names) — symbol references are too
# ambiguous for a reliable automated check (a symbol existing does not mean
# the task that references it is complete).
def _is_file_reference(ref: str) -> bool:
    return "/" in ref or "\\" in ref or ref.endswith(".md")


def find_drift(repo_root: Path) -> list[Drift]:
    changes_dir = repo_root / "openspec" / "changes"
    if not changes_dir.is_dir():
        return []

    tasks_files = list(changes_dir.glob("*/tasks.md"))
    if not tasks_files:
        return []

    all_drift: list[Drift] = []

    for tf in sorted(tasks_files):
        tfile = scan_tasks_md(tf)
        for cb in tfile.checkboxes:
            if cb.checked:
                continue

            # Only process lines with creation-intent language
            if not _CREATION_INTENT_RE.search(cb.text):
                continue

            refs = _BACKTICK_REF_RE.findall(cb.text)
            for ref in refs:
                ref = ref.strip()
                if not ref or len(ref) <= 1:
                    continue

                # Only check file-path references (not symbol names)
                if not _is_file_reference(ref):
                    continue

                if _file_exists(repo_root, ref):
                    all_drift.append(Drift(
                        file=tf,
                        line=cb.line,
                        kind="unchecked_creation_exists",
                        reference=ref,
                        message=(
                            f"[ ] task uses creation intent but `{ref}` already exists"
                        ),
                    ))

    return all_drift


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    drifts = find_drift(root)

    if not drifts:
        print("check_spec_drift: no drift detected")
        return 0

    print(f"check_spec_drift: {len(drifts)} drift(s) detected")
    for d in drifts:
        rel = d.file.relative_to(root)
        print(f"  [UNDECIDED_CREATION_EXISTS] {rel}:{d.line}  `{d.reference}`  {d.message}")

    return 1


if __name__ == "__main__":
    sys.exit(main())
