"""Test classification ratchet for APAP_WEB.

Enforces that for every domain that mocks SQL in unit tests, there is at
least one integration test against real Postgres when the flow involves
behaviour that mocks cannot verify.

Per ``docs/quality/test-audit.md`` (2026-08-31) and the
``apap-testing-strategy`` skill, the canonical gaps are:

    - ``entradas`` batch CTE rollback (P0)
    - ``cesiones`` conflict resolution (P0)
    - ``auth`` revalidation round-trip (P0)
    - chip cascade across animals/voluntarios/acogidas (P0)
    - ``animal_lifecycle_events`` append-only trigger (P0)

The ratchet locks this in: every domain whose unit tests mock SQL must
have either:

  1. A matching ``tests/integration/test_<modulo>_queries_integration.py``, or
  2. An explicit entry in the ``BASELINE`` mapping module name -> rationale.

This is a shrink-only ratchet: entries may only be removed when the
matching integration file lands. Adding a unit test for a flow that the
audit flagged as P0 without the matching integration test is a regression
and fails the gate.

The list of in-scope domains is **curated from the audit** — it is not
discovered by file-name heuristics, because too many unit tests in this
repo exercise pure functions or meta-tests that do not warrant integration
coverage.

Usage::

    python scripts/check_test_classification.py [root]

``root`` defaults to the repository root. Exit code 0 when clean, 1 on any
violation. Stdlib-only, deterministic, no external services.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = REPO_ROOT / "tests"
INTEGRATION_DIR = TESTS_DIR / "integration"

# Domains that have unit tests mocking SQL via httpx.MockTransport AND
# whose flows involve behaviour that httpx.MockTransport cannot verify
# against real Postgres (FK enforcement, triggers, CTE rollback,
# ON CONFLICT, soft-delete cascade).
#
# The list is curated from docs/quality/test-audit.md (2026-08-31). To add
# a new entry you must:
#   1. Land the integration file under tests/integration/ in the same PR.
#   2. Update docs/quality/test-audit.md to remove the gap.
#   3. Remove the matching BASELINE entry in this script (or move it to
#      COVERED once the integration file exists).
#
# This list is intentionally narrow — pure functions, helpers, route-layer
# contract tests, and meta-tests do not belong here. The skill
# ``apap-testing-strategy`` is the norm that defines the cut.
IN_SCOPE_DOMAINS: set[str] = {
    "acogidas",
    "adopciones",
    "auth",
    "cesiones",
    "entradas",
    "materiales",
    "salud",
    "sanidad",
}

# Domains that legitimately have only unit coverage at the moment.
# Each entry is (module_name, reason).
#
# A domain is "baselined" when:
#   - It is in IN_SCOPE_DOMAINS, AND
#   - It has unit tests that mock SQL, AND
#   - It does NOT have a matching integration file.
#
# The reason must cite docs/quality/test-audit.md so the BASELINE stays
# traceable to its source of truth.
BASELINE: dict[str, str] = {
    "cesiones": (
        "Conflict resolution (overlapping contratos, dual propietario) is exercised "
        "only at the route layer with a spy. The CTE rollback against a real "
        "UniqueViolationError is not asserted. See docs/quality/test-audit.md "
        "§Critical-gaps point 4."
    ),
    "auth": (
        "Auth revalidation against real DB (issue #143 path) is mocked via "
        "auth_reval_rows. The cookie + DB revalidation end-to-end round-trip "
        "is not asserted against real Postgres. See docs/quality/test-audit.md "
        "§Critical-gaps point 3."
    ),
}


def _has_integration_file(integration_dir: Path, module: str) -> bool:
    """Return True if there is an integration test for ``module``."""
    if not integration_dir.exists():
        return False
    target = integration_dir / f"test_{module}_queries_integration.py"
    return target.exists()


def check_tree(root: Path) -> tuple[list[str], list[str]]:
    """Return (violations, notices) for the test-classification ratchet."""
    integration_dir = root / "tests" / "integration"
    violations: list[str] = []
    open_baselined: set[str] = set()
    for module in sorted(IN_SCOPE_DOMAINS):
        if _has_integration_file(integration_dir, module):
            continue
        if module in BASELINE:
            open_baselined.add(module)
            continue
        violations.append(
            f"{module}: in scope for integration coverage (unit tests mock SQL "
            f"with httpx.MockTransport) but no "
            f"tests/integration/test_{module}_queries_integration.py found. "
            f"Add an integration atom (or BASELINE with rationale citing "
            f"docs/quality/test-audit.md)."
        )
    # Notices:
    # - BASELINE modules whose gap is still open (no integration file).
    # - BASELINE modules no longer in IN_SCOPE_DOMAINS (stale).
    notices = [
        f"{key}: baselined -- create tests/integration/test_{key}_queries_integration.py "
        f"to lock in the improvement. Reason: {BASELINE[key]}"
        for key in sorted(open_baselined)
    ] + [
        f"{key}: stale BASELINE entry (not in IN_SCOPE_DOMAINS) -- remove "
        f"from scripts/check_test_classification.py. Reason was: {BASELINE[key]}"
        for key in sorted(set(BASELINE) - IN_SCOPE_DOMAINS)
    ]
    return violations, notices


def _pin_output_encoding() -> None:
    """Pin stdout/stderr to UTF-8: output must not depend on the locale (issue #488)."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    _pin_output_encoding()
    root = Path(args[0]).resolve() if args else REPO_ROOT

    violations, notices = check_tree(root)

    for notice in notices:
        print(f"NOTE {notice}")
    for violation in violations:
        print(f"FAIL {violation}")

    if violations:
        print(
            f"check_test_classification: {len(violations)} violation(s). Every "
            f"domain whose unit tests mock SQL must have an integration atom "
            f"against real Postgres when the flow involves FK enforcement, "
            f"triggers, CTE rollback, or ON CONFLICT. See "
            f"docs/quality/test-audit.md."
        )
        return 1
    open_baseline_count = sum(
        1 for n in notices if "baselined --" in n
    )
    print(
        f"check_test_classification: OK "
        f"({open_baseline_count} baselined gap(s) still open; "
        f"shrink by landing the matching integration file)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
