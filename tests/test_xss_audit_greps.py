"""Round-2 grep acceptance criteria for Slice 4 (hardening-2026-q2).

The audit acceptance criteria added in round-2 judgment-day fixes
require the audit slice itself not to introduce raw ``logger.*``
calls into ``app/main.py`` or ``app/core/session.py``. PR-1A's AST
linter (``Detector 2`` from the design) enforces the same property
going forward, but PR-1A is not yet merged to staging; this file
inlines the grep so the audit slice ships a green check on its own
diff.

The second acceptance criterion (PR-1A's ``scripts/check_rules.py``
returning zero findings) is pending PR-1A's merge; the audit doc
records this as a known limitation and will be re-verified when
PR-1A lands.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_no_raw_logger_calls_in_main_or_session() -> None:
    """``app/main.py`` and ``app/core/session.py`` MUST NOT call ``logger.*`` directly.

    Mirrors PR-1A's AST linter (Detector 2) and Slice 6's APAP003 ruff
    rule. PR-XSS does not touch logging at all, so a grep over the
    two files returns zero matches — confirming the audit slice did
    not regress the log-call surface area.

    Note: ``app/core/logging.py`` is intentionally excluded (it owns
    the structured logging module; Slice 6 introduces it).
    """
    pattern = re.compile(r"\blogger\.(info|warning|error|debug|critical|exception)\b")
    targets = [
        REPO_ROOT / "app" / "main.py",
        REPO_ROOT / "app" / "core" / "session.py",
    ]
    offenders: list[str] = []
    for path in targets:
        if not path.exists():
            offenders.append(f"{path}: file missing")
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")
    assert offenders == [], (
        "XSS slice FAILED: raw logger.* call in app/main.py or app/core/session.py. "
        "Use app/core/logging.log_safe(...) once Slice 6 lands. Offending lines:\n"
        + "\n".join(offenders)
    )


def test_pr1a_ast_linter_passes_or_pending() -> None:
    """When ``scripts/check_rules.py`` lands, it MUST pass on PR-XSS.

    PR-1A's linter is the source of truth for the four rule detectors
    (Rule 1, 6, 7, 4-partial). PR-XSS does not introduce violations of
    any of them — it only adds new test files and an audit doc, neither
    of which is scanned by the linter (the linter walks ``app/**``).

    The linter file does not exist on staging yet (PR-1A is open but
    not merged). When it does, this test should pass; until then, this
    test is marked pending and skipped. We do NOT block the PR-XSS
    merge on a missing linter.
    """
    linter = REPO_ROOT / "scripts" / "check_rules.py"
    if not linter.exists():
        pytest_skip_pending_pr1a()
        return  # unreachable

    result = subprocess.run(
        [sys.executable, str(linter), str(REPO_ROOT / "app")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"PR-1A's check_rules.py flagged findings on PR-XSS:\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


def pytest_skip_pending_pr1a() -> None:
    """Skip helper that documents the pending PR-1A dependency."""
    import pytest

    pytest.skip(
        "PR-1A's scripts/check_rules.py is not yet on staging; "
        "this assertion will activate when PR-1A merges. "
        "See docs/audits/xss-audit-2026-Q2.md §Known Limitations."
    )
