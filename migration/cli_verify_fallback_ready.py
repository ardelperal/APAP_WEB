"""Standalone entry point for the verify-fallback-ready gate.

This module is the entry point the operator runs as
``python -m migration.cli_verify_fallback_ready`` (or via the
``apap-migrate`` shim). It does NOT import ``migration.cli`` because
the project CLI module has been fragmented by previous refactors and
is currently missing several ``run_*`` functions (apply, status,
ensure-bucket, verify-fallback-ready). The standalone path here
implements the gate directly via the ``migration.verify_fallback_ready``
helpers, without depending on the broken CLI module.

The gate is the closure of the migration openspec's M2 fallback-ready
requirement (PR7). Exit 0 when every CI-runnable condition passes;
exit 1 otherwise. The CI subset is the mode the CI job uses; the
full mode is invoked by the operator after a real migration cycle.

When the project's ``migration.cli`` is restored to a working state
(the fragmented functions are re-implemented), this module can be
folded back into the CLI's subparser as a regular subcommand.
"""

from __future__ import annotations

import argparse
import sys

from migration.verify_fallback_ready import format_receipt, run_gate


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="migration.cli_verify_fallback_ready",
        description=(
            "Verify the M2 fallback-ready gate (PR7). Exits 0 when "
            "every required check passes; exit 1 otherwise. The "
            "--ci-only mode is wired into .github/workflows/ci.yml."
        ),
    )
    p.add_argument(
        "--ci-only",
        action="store_true",
        help=(
            "Run only CI-runnable checks (no operator attestation). "
            "This is the mode the CI job uses."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    exit_code, results = run_gate(ci_only=args.ci_only)
    print(format_receipt(results, ci_only=args.ci_only))
    return exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
