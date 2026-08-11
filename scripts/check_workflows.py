"""Workflow-file gate: two ways a workflow stops protecting anything.

**Duplicate mapping keys (issue #523).** A workflow whose YAML does not parse
never becomes a red check. GitHub records a `startup_failure` run and the check
simply never appears in the pull request's status rollup, so the branch reads as
green while a required gate did not run. That is exactly how `pr-size`
disappeared on PR #522: a step was inserted between `uses: actions/checkout` and
its `with:` block, leaving two `with:` keys in one step.

`yaml.safe_load` would NOT have caught that one — PyYAML accepts duplicate keys
and keeps the last. So this check stays a stdlib indentation scanner over the
block-mapping subset these files actually use, and it runs FIRST: a file that
does not parse deterministically has nothing else worth asserting about it.

**Missing job timeouts (issue #529).** GitHub's default is 360 minutes. On
2026-08-11 three jobs sat queued against a wedged self-hosted runner; with a
single-runner pool that would have held the queue for six hours had nobody been
watching. Every job must state its own budget. This check parses properly with
PyYAML, which #526 moved into the ``dev`` extra precisely so the gates may.

Both checks prove they scanned something, per Hard Rule 18: zero workflow files
found is a failure, not a pass.
"""
from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

#: Block-scalar indicators. Everything indented under one of these is opaque
#: text (a shell script, usually) and must not be scanned for keys.
_BLOCK_INDICATORS = frozenset({"|", ">", "|-", ">-", "|+", ">+"})

#: One parsed mapping entry: line number, indent, whether it opens a list item,
#: key, and the raw value text that followed the colon.
Entry = tuple[int, int, bool, str, str]


def _split_key(content: str) -> tuple[str, str] | None:
    """Return ``(key, value)`` when ``content`` opens a mapping entry, else None.

    Only bare keys count. A quoted key or a URL inside a value never matches,
    which keeps the scanner from inventing keys out of ``run:`` script bodies
    that slipped past the block-scalar skip.
    """
    head, separator, tail = content.partition(":")
    if not separator or not head:
        return None
    if not (head[0].isalpha() or head[0] == "_"):
        return None
    if not all(character.isalnum() or character in "_-." for character in head):
        return None
    if tail and not tail.startswith(" "):
        return None  # e.g. `https://example.com` inside a plain value
    return head, tail.strip()


def _strip_item_marker(content: str, indent: int) -> tuple[str, int, bool]:
    """Return ``(content, indent, is_item)`` with any ``- `` list marker removed.

    A list item opens its own mapping two columns in, so ``- name: x`` declares
    ``name`` at ``indent + 2``, not at ``indent``.
    """
    if content == "-":
        return "", indent + 2, True
    if content.startswith("- "):
        return content[2:], indent + 2, True
    return content, indent, False


def _entries(text: str) -> Iterator[Entry]:
    """Yield every mapping entry in ``text``, skipping what cannot declare one.

    Blank lines, comments, and block-scalar bodies (the shell script under a
    ``run: |``) are dropped here so the caller only ever sees real keys.
    """
    block_indent: int | None = None
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        content = line.lstrip()
        indent = len(line) - len(content)

        if block_indent is not None:
            if not content or indent > block_indent:
                continue
            block_indent = None

        if not content or content.startswith("#"):
            continue

        content, key_indent, is_item = _strip_item_marker(content, indent)
        parsed = _split_key(content)
        if parsed is None:
            continue

        key, value = parsed
        if value in _BLOCK_INDICATORS:
            block_indent = key_indent
        yield number, key_indent, is_item, key, value


def _scope_for(stack: list[tuple[int, dict[str, int]]], indent: int, is_item: bool) -> dict[str, int]:
    """Return the mapping an entry at ``indent`` belongs to, opening one if needed.

    Deeper mappings are closed first. A list item additionally closes the
    mapping of the previous item, so two sibling steps may each declare
    ``name`` without colliding.
    """
    while stack and stack[-1][0] > indent:
        stack.pop()
    while is_item and stack and stack[-1][0] >= indent:
        stack.pop()
    if not stack or stack[-1][0] < indent:
        stack.append((indent, {}))
    return stack[-1][1]


def check_text(text: str, label: str) -> list[str]:
    """Return one violation per duplicate key found in a single workflow file."""
    violations: list[str] = []
    stack: list[tuple[int, dict[str, int]]] = []

    for number, indent, is_item, key, _value in _entries(text):
        keys = _scope_for(stack, indent, is_item)
        first = keys.get(key)
        if first is None:
            keys[key] = number
            continue
        violations.append(
            f"{label}:{number}: duplicate key '{key}' in the same block "
            f"(first seen on line {first}). GitHub rejects the file and the "
            f"check silently vanishes from the PR instead of failing."
        )

    return violations


def check_timeouts(text: str, label: str) -> list[str]:
    """Return one violation per job in ``text`` that states no ``timeout-minutes``.

    Only reached for files that already passed the duplicate-key scan, so
    ``yaml.safe_load`` here is parsing something known to be unambiguous.
    """
    workflow = yaml.safe_load(text)
    if not isinstance(workflow, dict):
        return []
    jobs = workflow.get("jobs") or {}
    return [
        f"{label}: job '{name}' declares no timeout-minutes — GitHub then applies "
        f"its 360-minute default, so a wedged runner holds the queue for six "
        f"hours instead of failing (issue #529)."
        for name, job in jobs.items()
        if isinstance(job, dict) and job.get("timeout-minutes") is None
    ]


def check(workflow_dir: Path = WORKFLOW_DIR) -> tuple[list[str], int]:
    """Return (violations, files scanned) for every workflow in ``workflow_dir``."""
    violations: list[str] = []
    paths = sorted(workflow_dir.glob("*.yml")) + sorted(workflow_dir.glob("*.yaml"))
    for path in paths:
        label = path.name
        if path.is_relative_to(REPO_ROOT):
            label = path.relative_to(REPO_ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        duplicates = check_text(text, label)
        violations.extend(duplicates)
        # A file whose keys are ambiguous cannot be reasoned about further: the
        # parser below would silently pick one of the colliding values.
        if not duplicates:
            violations.extend(check_timeouts(text, label))
    return violations, len(paths)


def _pin_output_encoding() -> None:
    """Pin stdout/stderr to UTF-8: output must not depend on the locale (issue #488)."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Run the gate over ``argv[0]`` (default: this repository's workflow dir)."""
    _pin_output_encoding()
    args = sys.argv[1:] if argv is None else argv
    if len(args) > 1:
        print("usage: check_workflows.py [workflow-dir]")
        return 2
    workflow_dir = Path(args[0]) if args else WORKFLOW_DIR

    if not workflow_dir.is_dir():
        print(f"FAIL {workflow_dir}: workflow directory not found")
        return 1

    violations, scanned = check(workflow_dir)
    for violation in violations:
        print(f"FAIL {violation}")
    if violations:
        return 1
    if scanned == 0:
        # Liveness: a gate that scanned nothing has proven nothing (#519).
        print(f"FAIL {workflow_dir}: no workflow files found — the gate scanned nothing")
        return 1
    print(
        f"check_workflows: OK ({scanned} workflow files, no duplicate keys, "
        f"every job has a timeout)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
