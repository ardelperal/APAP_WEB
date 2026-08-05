"""
HTML accessibility check for form label associations.

Checks that every <input>, <select>, and <textarea> in Jinja templates
has an `id` attribute and a matching `<label for="...">` element.

Run: python scripts/check_html_labels.py app/templates
Exits 1 if any form control lacks a label association.
Exits 0 if no issues found.

Per the issue #391 acceptance criteria: a mandatory guard so this cannot regress.
The check excludes hidden inputs (type="hidden") which are not user-fillable.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import NamedTuple

from bs4 import BeautifulSoup, FeatureNotFound  # noqa: I001


class Finding(NamedTuple):
    file: str
    line: int
    kind: str  # "control_no_id" | "label_no_control"
    detail: str


# -------------------------------------------------------------------
# Pre-processing: strip Jinja2 directives that confuse HTML parsers
# -------------------------------------------------------------------

JINJA_BLOCK = re.compile(r'\{%.*?%\}|\{\{.*?\}\}')
JINJA_COMMENT = re.compile(r'\{#.*?#\}')


def strip_jinja(content: str) -> str:
    """Remove Jinja2 blocks and expressions that would confuse the HTML parser."""
    return JINJA_COMMENT.sub(' ', JINJA_BLOCK.sub(' ', content))


# -------------------------------------------------------------------
# Extract all label FOR targets in a file
# -------------------------------------------------------------------

def get_label_targets(soup: BeautifulSoup) -> dict[str, str]:
    """
    Return dict of id_value -> label_text for all <label for='id'> elements.
    """
    targets: dict[str, str] = {}
    for label in soup.find_all('label'):
        fid = label.get('for')
        if fid and isinstance(fid, str):
            text = label.get_text(strip=True)[:60]
            targets[fid] = text
    return targets


# -------------------------------------------------------------------
# Extract all form controls with their id and name
# -------------------------------------------------------------------

def is_hidden_input(ctrl: dict) -> bool:
    return ctrl['tag'] == 'input' and ctrl.get('type', 'text').lower() == 'hidden'


def find_controls(soup: BeautifulSoup) -> list[dict]:
    """
    Return list of dicts with keys: tag, line, id (or None), name (or None), type (for inputs).
    """
    results: list[dict] = []
    for tag in soup.find_all(['input', 'select', 'textarea']):
        ctrl: dict = {
            'tag': tag.name,
            'line': tag.sourceline if hasattr(tag, 'sourceline') else 0,
            'id': tag.get('id'),
            'name': tag.get('name'),
        }
        if tag.name == 'input':
            ctrl['type'] = tag.get('type', 'text')
        results.append(ctrl)
    return results


# -------------------------------------------------------------------
# Check a single file
# -------------------------------------------------------------------

def check_file(path: Path) -> list[Finding]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    clean = strip_jinja(raw)

    try:
        soup = BeautifulSoup(clean, 'html.parser')
    except FeatureNotFound:
        soup = BeautifulSoup(clean, 'lxml')

    findings: list[Finding] = []
    controls = find_controls(soup)
    label_targets = get_label_targets(soup)

    for ctrl in controls:
        # Skip hidden inputs — not user-fillable, SonarQube doesn't flag them
        if is_hidden_input(ctrl):
            continue

        ctrl_id = ctrl['id']
        ctrl_name = ctrl['name']
        line = ctrl['line']
        tag = ctrl['tag']

        if ctrl_id is None:
            # No id at all — if it has a name, it's a user-fillable control needing an id
            if ctrl_name:
                findings.append(Finding(
                    file=str(path),
                    line=line,
                    kind="control_no_id",
                    detail=f"<{tag} name=\"{ctrl_name}\"> has no id — no label can reference it",
                ))
            continue

        # Has an id — check if there's a corresponding label
        if ctrl_id not in label_targets:
            findings.append(Finding(
                file=str(path),
                line=line,
                kind="label_missing",
                detail=f"<{tag} id=\"{ctrl_id}\"> has no associated <label for=\"{ctrl_id}\">",
            ))

    return findings


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------

def main(root: Path) -> int:
    templates = sorted(root.rglob("*.html"))
    total_findings: list[Finding] = []

    for path in templates:
        findings = check_file(path)
        total_findings.extend(findings)

    # Group by file
    by_file: dict[str, list[Finding]] = {}
    for f in total_findings:
        by_file.setdefault(f.file, []).append(f)

    print(f"\nHTML label association check — {len(templates)} templates scanned\n")
    print(f"{'File':<60} {'Line':>5}  {'Kind':<20}  Detail")
    print("-" * 120)

    for _file, fds in sorted(by_file.items()):
        for fd in fds:
            print(f"{fd.file:<60} {fd.line:>5}  {fd.kind:<20}  {fd.detail}")

    print("-" * 120)
    total = len(total_findings)
    print(f"\nTotal findings: {total}")

    if total > 0:
        print(f"\n!! {total} accessibility issues found. Fix required before merge.")
        return 1
    print("\nAll form controls have proper label associations.")
    return 0


if __name__ == "__main__":
    _MIN_ARGS = 2
    if len(sys.argv) < _MIN_ARGS:
        print("Usage: python scripts/check_html_labels.py <templates_dir>")
        sys.exit(1)

    root = Path(sys.argv[1])
    if not root.exists():
        print(f"Error: {root} does not exist")
        sys.exit(1)

    sys.exit(main(root))
