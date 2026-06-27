"""AST-based rule linter for APAP_WEB AGENTS.md rules.

Per Slice 1 of the hardening-2026-q2 chain
(openspec/changes/hardening-2026-q2/specs/01-dev-tooling-gate/spec.md).

This module is the read-only gate that catches the four most common
violations of the project rules documented at AGENTS.md:300-308:

1. Rule 1 — Routes must not call ``client.execute_sql`` directly.
2. Rule 4 — DDL must not hardcode the role list in ``CHECK`` constraints.
3. Rule 6 — Auth defaults must be deny (``False``), not permit (``True``).
4. Rule 7 — Redirects are ``RedirectResponse``, not ``HTTPException``.

The linter uses Python's stdlib ``ast`` module (no third-party deps)
and exits non-zero on any violation, so it plugs into CI fail-fast
checks without ceremony.

Detectors are wired into the orchestrator in subsequent commits; this
scaffold exposes only the public types so callers (tests, CLI) can
import without crashing.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

# --- public types ----------------------------------------------------------


@dataclass(frozen=True)
class Violation:
    """A single rule violation found by the AST linter."""

    file: Path
    line: int
    rule_id: str
    message: str


# --- orchestrator (scaffold — detectors wire in over the next commits) -----


def find_violations(repo_root: Path) -> list[Violation]:
    """Scan the given directory tree and return all violations.

    Detectors land in subsequent commits:

    - commit 3: ``route_uses_execute_sql`` (Rule 1).
    - commit 4: ``auth_defaults_true`` (Rule 6), ``http_exception_redirect``
      (Rule 7), ``hardcoded_role_check_in_ddl`` (Rule 4 partial).

    Until then, this scaffold returns ``[]`` so callers can exercise the
    import contract without flagging anything.
    """
    if not repo_root.exists():
        return []
    return []


# --- CLI entry point ------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(
            "usage: python scripts/check_rules.py <path> [<path>...]",
            file=sys.stderr,
        )
        return 2
    all_violations: list[Violation] = []
    for arg in args:
        target = Path(arg).resolve()
        all_violations.extend(find_violations(target))
    if all_violations:
        for v in sorted(all_violations, key=lambda x: (str(x.file), x.line)):
            print(f"{v.file}:{v.line}: {v.rule_id}: {v.message}")
        print(
            f"\n{len(all_violations)} violation(s) across "
            f"{len({str(v.file) for v in all_violations})} file(s).",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
