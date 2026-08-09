"""Audit-doc and runbook convention checker (developer aid for AGENTS.md Rules 12 and 13).

This script flags changes to sensitive paths and suggests creating
``docs/audits/`` or ``docs/runbooks/`` entries. It is a **developer aid**,
not a CI gate — the convention is enforced at PR review time per
AGENTS.md Rules 12 and 13.

Usage::

    python scripts/check_audit_and_runbook.py [BASE_REF]

``BASE_REF`` defaults to ``origin/main``. The script compares the current
HEAD to ``BASE_REF`` and lists changes. Exit code is always 0 (this is
an aid, not a gate). If sensitive paths are touched, the script prints
suggestions for ``docs/audits/<feature>-audit-YYYY-Qn.md`` and/or
``docs/runbooks/<thing>.md``.

Rule mapping (per AGENTS.md):
- Rule 12 (audit doc): sensitive = auth, secrets, cookies, CSRF, XSS, idempotency, PII
- Rule 13 (runbook): sensitive = env-var changes (settings, config)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# Path prefixes that suggest an audit doc per Rule 12.
# Match the categories called out in AGENTS.md Rule 12: "auth, secrets,
# cookies, CSRF, XSS, idempotency, or PII".
SENSITIVE_AUDIT_PATHS: tuple[str, ...] = (
    "app/core/auth.py",
    "app/core/auth_dependencies.py",
    "app/core/csrf.py",
    "app/core/session.py",
    "app/core/logging.py",
    "app/core/migration/",
    "app/modules/",
    "app/main.py",  # middleware registration, lifespan, OAuth flow
    "tests/test_csrf_",
    "tests/test_auth_dependencies",
    "tests/test_session",
    "tests/test_logging",
    "tests/test_xss_",
    "tests/test_migration_",
    "tests/test_voluntarios_concurrent",  # TOCTOU/idempotency
)

# Path prefixes that suggest a runbook per Rule 13: "secret rotation,
# manual deploy step, cache invalidation, cron trigger, env-var change".
SENSITIVE_RUNBOOK_PATHS: tuple[str, ...] = (
    "app/core/config.py",  # env-var settings live here
    "app/core/csrf.py",  # APAP_CSRF_ENABLED is operator toggle
    "app/main.py",  # APAP_SESSION_SECRET rotation
    "Dockerfile",  # build/deploy changes
    ".github/workflows/",
    "Makefile",  # operator runnable commands
    "scripts/dev_",
    "scripts/migration_",
)


def _match_prefix(path: Path, prefixes: tuple[str, ...]) -> bool:
    """True if ``str(path)`` starts with any of the ``prefixes`` (POSIX)."""
    p = str(path).replace("\\", "/")
    return any(p == prefix or p.startswith(prefix.rstrip("/") + "/") for prefix in prefixes)


def _changed_files(base_ref: str) -> list[Path]:
    """Return the list of files changed between ``base_ref`` and HEAD."""
    result = subprocess.run(
        ["git", "diff", "--name-only", base_ref, "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [Path(f) for f in result.stdout.splitlines() if f]


def _check_audit(changed: list[Path]) -> list[Path]:
    """Return paths that match the audit-doc sensitive set (Rule 12)."""
    return [p for p in changed if _match_prefix(p, SENSITIVE_AUDIT_PATHS)]


def _check_runbook(changed: list[Path]) -> list[Path]:
    """Return paths that match the runbook sensitive set (Rule 13)."""
    return [p for p in changed if _match_prefix(p, SENSITIVE_RUNBOOK_PATHS)]


def _render_suggestions(audit_paths: list[Path], runbook_paths: list[Path]) -> str:
    """Render the user-facing suggestions block."""
    lines: list[str] = []
    if audit_paths:
        lines.append("Rule 12 — Audit doc suggested (per AGENTS.md):")
        for p in audit_paths:
            lines.append(f"  - {p}")
        lines.append(
            "    Create or update docs/audits/<feature>-audit-YYYY-Qn.md"
        )
        lines.append(
            "    Template: docs/audits/xss-audit-2026-Q2.md"
        )
        lines.append("")
    if runbook_paths:
        lines.append("Rule 13 — Runbook suggested (per AGENTS.md):")
        for p in runbook_paths:
            lines.append(f"  - {p}")
        lines.append(
            "    Create or update docs/runbooks/<thing>.md"
        )
        lines.append(
            "    Sections: When to trigger, Pre-deploy checklist,"
        )
        lines.append(
            "             Deploy steps, Verification, Rollback"
        )
        lines.append("")
    if not audit_paths and not runbook_paths:
        lines.append(
            "No sensitive changes detected. No audit doc or runbook required."
        )
    return "\n".join(lines)


def _pin_output_encoding() -> None:
    """Pin stdout/stderr to UTF-8: output must not depend on the locale (issue #488)."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _pin_output_encoding()
    parser = argparse.ArgumentParser(
        description=(
            "Suggest audit-doc and runbook creation per AGENTS.md "
            "Rules 12 and 13. Developer aid, not a CI gate."
        )
    )
    parser.add_argument(
        "base_ref",
        nargs="?",
        default="origin/main",
        help="Git ref to diff against (default: origin/main)",
    )
    args = parser.parse_args(argv)

    try:
        changed = _changed_files(args.base_ref)
    except subprocess.CalledProcessError as e:
        print(f"Error: {e.stderr}", file=sys.stderr)
        return 1

    audit_paths = _check_audit(changed)
    runbook_paths = _check_runbook(changed)
    print(_render_suggestions(audit_paths, runbook_paths))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
