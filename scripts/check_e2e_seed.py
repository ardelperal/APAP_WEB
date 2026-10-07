"""Fail-loud preflight for the E2E seed row (issue #1223).

The production e2e gate (#909/#1073) mints its session for
``e2e@apap.local`` against ``usuarios_autorizados``; when that row drifts
away (as it did on 2026-10-02), ``/e2e/login`` answers ``400`` and the
battery fails as an opaque "credential rejected". This preflight
verifies the precondition and fails loudly instead, so the operator
fixes the seed before the battery instead of triaging a 400.

The row is mutable production state; no automation guarantees it. This
script converts the silent failure into signal — it never seeds or
mutates anything.

Usage::

    python scripts/check_e2e_seed.py [--dsn DSN]

``--dsn`` defaults to the ``APAP_LOCAL_DB_URL`` environment variable.
Exit codes:
    0 - exactly one active ``developer`` row for the E2E email
    1 - precondition unmet (missing, inactive, wrong role, duplicated)
    2 - usage error (no DSN) or database error

Runbook: ``docs/runbooks/e2e-production.md``, precondition 6.
Tests: ``tests/test_check_e2e_seed.py``.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

EMAIL = "e2e@apap.local"
EXPECTED_ROLE = "developer"
QUERY = "SELECT email, rol, activo FROM usuarios_autorizados WHERE email = %s"
RUNBOOK = "docs/runbooks/e2e-production.md"
EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE_ERROR = 2


@dataclass(frozen=True)
class Verdict:
    """Outcome of the seed precondition check."""

    ok: bool
    message: str


def evaluate(rows: Sequence[Mapping[str, object]]) -> Verdict:
    """Decide whether ``rows`` satisfy the E2E seed precondition.

    ``rows`` holds every ``usuarios_autorizados`` row for the E2E email;
    the caller is responsible for the query, the decision for its shape.
    """
    if len(rows) == 0:
        return Verdict(
            ok=False,
            message=(
                f"precondition not seeded: no usuarios_autorizados row for {EMAIL}; "
                f"/e2e/login will answer 400 and the battery cannot run. Insert "
                f"('{EMAIL}', '{EXPECTED_ROLE}', true) per {RUNBOOK}, precondition 6."
            ),
        )
    if len(rows) > 1:
        return Verdict(
            ok=False,
            message=(
                f"precondition ambiguous: more than one usuarios_autorizados row for "
                f"{EMAIL}; the allowlist must hold exactly one. Inspect them per {RUNBOOK}."
            ),
        )
    row = rows[0]
    rol = str(row.get("rol"))
    activo = row.get("activo")
    if rol != EXPECTED_ROLE:
        return Verdict(
            ok=False,
            message=(
                f"precondition unmet: the {EMAIL} row has rol {rol!r}, expected "
                f"{EXPECTED_ROLE!r}; /e2e/login would mint the wrong capability. "
                f"Fix the row per {RUNBOOK}, precondition 6."
            ),
        )
    if activo is not True:
        return Verdict(
            ok=False,
            message=(
                f"precondition unmet: the {EMAIL} row is not active (activo={activo!r}); "
                f"/e2e/login resolves the email against active users only. "
                f"Fix the row per {RUNBOOK}, precondition 6."
            ),
        )
    return Verdict(
        ok=True,
        message=f"e2e seed row present for {EMAIL} (rol {EXPECTED_ROLE}, active).",
    )


def fetch_rows(dsn: str) -> list[Mapping[str, object]]:
    """Query every ``usuarios_autorizados`` row for the E2E email."""
    import psycopg

    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute(QUERY, (EMAIL,))
        columns = [description.name for description in cursor.description or []]
        return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _pin_output_encoding() -> None:
    """Pin stdout/stderr to UTF-8: output must not depend on the locale (issue #488)."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Run the preflight and translate the verdict into an exit code."""
    _pin_output_encoding()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dsn",
        default=None,
        help="production Postgres DSN (default: the APAP_LOCAL_DB_URL environment variable)",
    )
    args = parser.parse_args(argv)
    dsn = args.dsn or os.environ.get("APAP_LOCAL_DB_URL")
    if not dsn:
        print(
            f"::error::no DSN provided: pass --dsn or set APAP_LOCAL_DB_URL; "
            f"the {EMAIL} precondition cannot be verified without the database."
        )
        return EXIT_USAGE_ERROR
    try:
        rows = fetch_rows(dsn)
    except Exception as error:  # noqa: BLE001 - any DB failure must fail loudly
        print(f"::error::the seed check could not query the database: {error}")
        return EXIT_USAGE_ERROR

    verdict = evaluate(rows)
    if verdict.ok:
        print(f"::notice::{verdict.message}")
        return EXIT_OK
    print(f"::error::{verdict.message}")
    return EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
