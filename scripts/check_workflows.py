"""Workflow-file gate: six ways a workflow stops protecting anything.

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

**Fixed host ports on service containers (issue #532).** ``5432:5432`` reserves
a port on the runner host. One runner serialises the jobs, so nothing collides
and the defect stays invisible; a second runner turns it into two branches
sharing one database, which passes.

**A command the runner does not have (issue #533).** The hosted image shipped
the `gh` CLI and this one does not, so `gh api` exits 127. `deploy.yml` hid
that behind ``2>/dev/null || echo 0`` and every merge from d38b748 onward
silently refused to deploy, reporting a broken lookup as an unproven tree.

**No concurrency group (issue #530).** A second push runs alongside the
first and both compete for the single eligible runner, and
``cancel-in-progress: true`` would discard work that already consumed it.

**Unchecked Docker (issue #531).** `docker run` against a wedged daemon
BLOCKS rather than failing, so the job goes silent until its timeout. The
guard must be wrapped in ``timeout``, or it hangs the same way it is meant
to prevent.

**Missing job timeouts (issue #529).** GitHub's default is 360 minutes. On
2026-08-11 three jobs sat queued against a wedged self-hosted runner; with a
single-runner pool that would have held the queue for six hours had nobody been
watching. Every job must state its own budget. This check parses properly with
PyYAML, which #526 moved into the ``dev`` extra precisely so the gates may.

All six checks prove they scanned something, per Hard Rule 18: zero workflow files
found is a failure, not a pass.
"""
from __future__ import annotations

import re
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


def check_service_ports(text: str, label: str) -> list[str]:
    """Return one violation per service container bound to a fixed host port.

    ``5432:5432`` reserves a port on the runner host. With one runner in the pool
    the jobs serialise and nothing collides, so the defect is invisible and CI
    stays green. Add a second runner and two concurrent jobs either fail to bind
    or share one database across two branches — and the second outcome passes.
    Publishing the container port alone (``- 5432``) lets Docker choose.
    """
    workflow = yaml.safe_load(text)
    if not isinstance(workflow, dict):
        return []
    violations: list[str] = []
    for name, job in (workflow.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        for service, spec in (job.get("services") or {}).items():
            for port in (spec or {}).get("ports") or []:
                if ":" not in str(port):
                    continue
                violations.append(
                    f"{label}: job '{name}' service '{service}' pins host port "
                    f"'{port}'. Publish the container port alone and read the "
                    f"assigned one from job.services.{service}.ports (issue #532)."
                )
    return violations


#: Commands the GitHub-hosted images provide and this runner image does not.
#: Each one exits 127 here, and a step that swallows that turns it into a verdict.
_ABSENT_ON_RUNNER = ("gh",)

_INVOCATION = "|".join(_ABSENT_ON_RUNNER)
_INVOKES_ABSENT = re.compile(rf"(?:^|[|&;(`$]|\s)(?:{_INVOCATION})\s", re.MULTILINE)


def _executable_lines(script: str) -> str:
    """``script`` with comment-only lines removed.

    Comments in these workflows explain the very commands they must not invoke —
    the deploy evidence step documents the `gh api` it replaced — so a scan that
    reads them reports the explanation as the offence.
    """
    return "\n".join(
        line for line in script.splitlines() if not line.strip().startswith("#")
    )


def check_absent_commands(text: str, label: str) -> list[str]:
    """Return one violation per step invoking a command this runner does not have.

    The GitHub-hosted image shipped the `gh` CLI; the actions-runner image does
    not. `deploy.yml` called `gh api` behind `2>/dev/null || echo 0`, so the 127
    became `green=0` — "this tree was never proven" — and every merge from
    d38b748 onward refused to deploy without saying why (issue #533). Use
    `curl` + `jq`, both of which are present.
    """
    workflow = yaml.safe_load(text)
    if not isinstance(workflow, dict):
        return []
    violations: list[str] = []
    for name, job in (workflow.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        for script in _step_scripts(job):
            if _INVOKES_ABSENT.search(_executable_lines(script)):
                violations.append(
                    f"{label}: job '{name}' invokes a command the self-hosted "
                    f"runner does not provide ({', '.join(_ABSENT_ON_RUNNER)}). "
                    f"It exits 127, and a step that defaults on failure turns "
                    f"that into a verdict. Use curl + jq (issue #533)."
                )
                break
    return violations


def check_concurrency(text: str, label: str) -> list[str]:
    """Return violations when a workflow declares no FIFO concurrency group.

    The pool has one eligible runner and a runner executes one job at a time, so
    two runs of a branch interleave rather than overlap and neither finishes
    early. ``cancel-in-progress: true`` is the right default where capacity is
    elastic; here it discards work that already consumed the only runner.
    """
    workflow = yaml.safe_load(text)
    if not isinstance(workflow, dict):
        return []
    concurrency = workflow.get("concurrency")
    if not isinstance(concurrency, dict) or not concurrency.get("group"):
        return [
            f"{label}: declares no concurrency group, so a second push runs "
            f"alongside the first and both compete for the single runner "
            f"(issue #530)."
        ]
    if concurrency.get("cancel-in-progress") is not False:
        return [
            f"{label}: concurrency must set cancel-in-progress: false. "
            f"Cancelling discards a run that already consumed the only runner "
            f"in the pool, and for deploy it can leave the target half-updated "
            f"(issue #530)."
        ]
    return []


def _step_scripts(job: dict) -> list[str]:
    """The ``run:`` body of each step in order; steps without one contribute ''."""
    return [str(step.get("run") or "") for step in (job.get("steps") or []) if isinstance(step, dict)]


def check_docker_preflight(text: str, label: str) -> list[str]:
    """Return one violation per job that reaches ``docker run`` with no live daemon check.

    A wedged daemon makes ``docker run`` block rather than fail, so the job goes
    silent until its timeout. The check must be wrapped in ``timeout``: a bare
    ``docker info`` hangs the same way, and a preflight that can hang is not one.
    """
    workflow = yaml.safe_load(text)
    if not isinstance(workflow, dict):
        return []
    violations: list[str] = []
    for name, job in (workflow.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        scripts = _step_scripts(job)
        first_run = next((i for i, s in enumerate(scripts) if "docker run" in s), None)
        if first_run is None:
            continue
        guarded = any(
            "docker info" in script and "timeout" in script for script in scripts[:first_run]
        )
        if not guarded:
            violations.append(
                f"{label}: job '{name}' reaches `docker run` with no preceding "
                f"`timeout <n> docker info` check. A wedged daemon then blocks "
                f"instead of failing, and the job goes silent until its timeout "
                f"(issue #531)."
            )
    return violations


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
            violations.extend(check_service_ports(text, label))
            violations.extend(check_docker_preflight(text, label))
            violations.extend(check_concurrency(text, label))
            violations.extend(check_absent_commands(text, label))
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
        f"every job has a timeout, no pinned service ports, docker is checked "
        f"before use, FIFO concurrency, no absent commands)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
