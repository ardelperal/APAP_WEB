#!/usr/bin/env python3
"""
Fix WCAG label/input associations in Jinja2 templates.

Uses direct character scanning to handle multi-line HTML tags with Jinja expressions.

Pass 1: add id="<name>" to controls (input/select/textarea) that have name= but no id=
Pass 2: add for="<name>" to labels that lack it, by looking ahead for the matching control id=

Usage:
    python scripts/fix_form_labels.py [--dry-run]
"""
import sys
from pathlib import Path

TEMPLATES_DIR = Path("app/templates")


# -------------------------------------------------------------------
# HTML scanning helpers
# -------------------------------------------------------------------

def find_tag_end(content: str, start: int) -> int:
    """
    Find the closing > of an opening tag starting at position `start` (position of <).
    Stops at the first > NOT inside single/double quotes and NOT inside Jinja {{ }} expressions.
    Returns position AFTER the closing >.
    """
    i = start + 1  # after '<'
    while i < len(content):
        c = content[i]
        if c in {'"', "'"}:
            q = c
            i += 1
            while i < len(content):
                if content[i] == '\\' and i + 1 < len(content):
                    i += 2
                    continue
                if content[i] == q:
                    i += 1
                    break
                i += 1
        elif c == '>':
            # If the preceding non-whitespace char is '}', we are inside a Jinja {{ }}
            # expression (e.g. value="{{ csrf_token }}") — keep scanning.
            j = i - 1
            while j >= start + 1 and content[j] in ' \t':
                j -= 1
            if j >= start + 1 and content[j] == '}':
                i += 1
                continue
            return i + 1
        else:
            i += 1
    return -1


def find_close_tag(content: str, start: int, tag_name: str) -> int:
    """Find </tag_name> starting from `start`. Returns position AFTER the closing tag."""
    search = f'</{tag_name}'
    i = start
    while i < len(content):
        pos = content.find(search, i)
        if pos == -1:
            return -1
        end = pos + len(search)
        if end >= len(content) or content[end] in ' \t\n\r':
            return end
        i = end
    return -1


def get_attr(content: str, start: int, end: int, attr: str) -> str | None:  # noqa: C901
    """Get value of attribute `attr` in content[start:end] (a tag)."""
    region = content[start:end]
    i = 0
    while i < len(region):
        while i < len(region) and region[i] not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ':
            i += 1
        if i >= len(region):
            break
        j = i
        while j < len(region) and region[j] not in '= \t\n\r/>':
            j += 1
        word = region[i:j]
        if word == attr and j < len(region) and region[j] == '=':
            val_start = j + 1
            while val_start < len(region) and region[val_start] in ' \t':
                val_start += 1
            if val_start >= len(region):
                return None
            q = region[val_start]
            if q in '"\'':
                val_start += 1
                val_end = val_start
                while val_end < len(region):
                    if region[val_end] == '\\':
                        val_end += 2
                        continue
                    if region[val_end] == q:
                        return region[val_start:val_end]
                    val_end += 1
                return None
            val_end = val_start
            while val_end < len(region) and region[val_end] not in ' \t\n\r/>':
                val_end += 1
            return region[val_start:val_end]
        i = j
    return None


def is_void_tag(tag_name: str) -> bool:
    return tag_name.lower() in {'input', 'br', 'hr', 'img', 'meta', 'link'}


# -------------------------------------------------------------------
# Control processing
# -------------------------------------------------------------------

def find_controls(content: str):
    """Yield (start, end_after_tag, name) for each form control with name=."""
    i = 0
    while i < len(content):
        if content[i] != '<':
            i += 1
            continue
        # Skip closing tags
        if content[i:i+2] == '</':
            j = content.find('>', i)
            i = j + 1 if j != -1 else i + 1
            continue
        # Extract tag name
        j = i + 1
        while j < len(content) and content[j].isalpha():
            j += 1
        tag_name = content[i+1:j]
        if tag_name.lower() not in {'input', 'select', 'textarea'}:
            i += 1
            continue
        # Find end of opening tag
        tag_end = find_tag_end(content, i)
        if tag_end == -1:
            i += 1
            continue
        name = get_attr(content, i, tag_end, 'name')
        if name is None:
            i = tag_end
            continue
        # For container tags (select/textarea), find closing tag
        end_pos = tag_end
        if tag_name.lower() == 'select' or tag_name.lower() == 'textarea':
            close_end = find_close_tag(content, tag_end, tag_name.lower())
            if close_end != -1:
                end_pos = close_end
        yield (i, end_pos, name)
        i = end_pos


def control_has_id(content: str, start: int, end: int, name: str) -> bool:
    return f'id="{name}"' in content[start:end]


def add_id_to_control(content: str, start: int, end: int, name: str) -> str:
    """Insert id="<name>" before name="<name>" in a control tag."""
    region = content[start:end]
    name_attr = f'name="{name}"'
    name_pos = region.find(name_attr)
    if name_pos == -1:
        return content
    # Insert id="..." just before name_attr
    insert_at = start + name_pos
    return content[start:insert_at] + f'id="{name}" ' + content[insert_at:end]


# -------------------------------------------------------------------
# Label processing
# -------------------------------------------------------------------

def find_label_closes(content: str, start: int) -> tuple[int, int] | None:
    """
    Find </label> for a label starting at `start`.
    Returns (pos_after_close_tag, end_pos) or None.
    """
    search = '</label>'
    i = start
    while i < len(content):
        pos = content.find(search, i)
        if pos == -1:
            return None
        end = pos + len(search)
        # Make sure </label> is not inside quotes
        region = content[start:pos]
        in_str = False
        for ch in region:
            if ch in '"\'':
                in_str = not in_str
        if in_str:
            i = end
            continue
        return (pos, end)
    return None


def fix_labels(content: str) -> tuple[str, int]:  # noqa: C901
    """Add for= to labels that lack it."""
    count = 0
    out: list[str] = []
    i = 0
    while i < len(content):
        # Find next <label (must be at position of '<')
        label_pos = content.find('<label', i)
        if label_pos == -1:
            out.append(content[i:])
            break
        # Must be preceded by whitespace or start of string
        if label_pos > 0 and content[label_pos - 1] not in ' \t\n\r':
            # 'label' appears in class="text-label" etc — skip
            out.append(content[i:label_pos + 6])
            i = label_pos + 6
            continue
        # Text before this label
        out.append(content[i:label_pos])
        # Find end of opening <label ...>
        tag_end = find_tag_end(content, label_pos)
        if tag_end == -1:
            out.append(content[label_pos:])
            break
        opening = content[label_pos:tag_end]
        # Find </label>
        close = find_label_closes(content, tag_end)
        if close is None:
            out.append(content[label_pos:])
            break
        close_pos, close_end = close
        if 'for=' not in opening:
            # Look ahead for a control with id=
            scan_start = close_end
            matched_name: str | None = None
            for c_start, c_end, c_name in find_controls(content[scan_start:]):
                abs_start = scan_start + c_start
                abs_end = scan_start + c_end
                if control_has_id(content, abs_start, abs_end, c_name):
                    matched_name = c_name
                    break
            if matched_name:
                # Insert for= in opening tag (after <label)
                # e.g. <label class="...">text</label> → <label for="X" class="...">text</label>
                insert_pos = label_pos + 6
                while insert_pos < tag_end and content[insert_pos] in ' \t':
                    insert_pos += 1
                out.append(content[label_pos:insert_pos])
                out.append(f'for="{matched_name}" ')
                out.append(content[insert_pos:tag_end])
                out.append(content[tag_end:close_end])
                count += 1
                i = close_end
                continue
        # Keep label as-is
        out.append(content[label_pos:close_end])
        i = close_end
    return ''.join(out), count


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------

def fix_template(file_path: Path, dry_run: bool = False) -> tuple[int, int]:
    content = file_path.read_text(encoding="utf-8")
    original = content

    controls_fixed = 0
    labels_fixed = 0

    # Pass 1: add id= to controls
    parts: list[str] = []
    last = 0
    for c_start, c_end, c_name in find_controls(content):
        region = content[c_start:c_end]
        if 'type="hidden"' in region.lower():
            parts.append(content[last:c_end])
            last = c_end
            continue
        if control_has_id(content, c_start, c_end, c_name):
            parts.append(content[last:c_end])
            last = c_end
            continue
        # Add id=
        parts.append(content[last:c_start])
        parts.append(add_id_to_control(content, c_start, c_end, c_name))
        last = c_end
        controls_fixed += 1
    parts.append(content[last:])
    content = ''.join(parts)

    # Pass 2: fix labels
    content, labels_fixed = fix_labels(content)

    if dry_run:
        return labels_fixed, controls_fixed

    if content != original:
        file_path.write_text(content, encoding="utf-8")

    return labels_fixed, controls_fixed


def _pin_output_encoding() -> None:
    """Pin stdout/stderr to UTF-8: output must not depend on the locale (issue #488)."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")


def main():
    _pin_output_encoding()
    dry_run = "--dry-run" in sys.argv
    total_labels = 0
    total_controls = 0

    for tpl in sorted(TEMPLATES_DIR.rglob("*.html")):
        labels, controls = fix_template(tpl, dry_run=dry_run)
        if labels or controls:
            mode = "DRY" if dry_run else "Fixed"
            print(f"{mode}: {tpl}: {labels} labels, {controls} controls")
        total_labels += labels
        total_controls += controls

    print(f"\n{'Dry run' if dry_run else 'Total'}: {total_labels} labels, {total_controls} controls")


if __name__ == "__main__":
    main()
