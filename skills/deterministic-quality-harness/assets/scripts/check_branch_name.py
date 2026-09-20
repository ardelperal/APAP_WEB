#!/usr/bin/env python3
# HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — assets/scripts/check_branch_name.py
"""Branch-name gate.

A branch whose name does not carry its type and its issue number is unreadable two years later,
which is exactly when someone needs to read it.

Exit codes:
    0  branch name matches the pattern, or is allowlisted
    1  anything else
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

# --------------------------------------------------------------------------------------------
# CONFIGURATION
# --------------------------------------------------------------------------------------------

PATTERN = re.compile(r"^(feat|fix|refactor|docs|ci|test|chore)/\d+-[a-z0-9]+(-[a-z0-9]+)*$")

#: Long-lived branches that predate or transcend the convention.
ALLOWLIST = frozenset({"main"})

# --------------------------------------------------------------------------------------------
# MECHANISM
# --------------------------------------------------------------------------------------------


def current_branch() -> str:
    for env_var in ("BRANCH_NAME", "GITHUB_HEAD_REF"):
        value = os.environ.get(env_var, "").strip()
        if value:
            return value
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git rev-parse failed")
    return result.stdout.strip()


def _pin_output_encoding() -> None:
    """Pin stdout/stderr to UTF-8.

    Python picks the output encoding from the platform locale, so the same gate emits different
    bytes on a Windows workstation (cp1252) and a Linux runner (utf-8) — and a non-encodable
    character crashes the write outright. A harness that claims determinism cannot let its own
    output depend on where it ran.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _pin_output_encoding()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--branch", default=None, help="branch name to check (default: detected)")
    parser.add_argument("--json", action="store_true", help="emit the indicator envelope")
    args = parser.parse_args(argv)

    try:
        branch = args.branch or current_branch()
    except RuntimeError as exc:
        message = f"could not determine the branch name: {exc}"
        if args.json:
            print(json.dumps({"gate": "branch_name", "status": "error", "detail": message}))
        else:
            print(f"FAIL  {message}", file=sys.stderr)
        return 1

    if args.json:
        conformant = branch in ALLOWLIST or bool(PATTERN.match(branch))
        print(
            json.dumps(
                {
                    "gate": "branch_name",
                    "status": "pass" if conformant else "fail",
                    "indicators": {"conformant": int(conformant)},
                    "ceilings": {"conformant": 1},
                    "findings": []
                    if conformant
                    else [
                        {
                            "file": "<branch>",
                            "line": 0,
                            "detail": f"'{branch}' does not match {PATTERN.pattern}",
                        }
                    ],
                },
                indent=2,
            )
        )
        return 0 if conformant else 1

    if branch in ALLOWLIST:
        print(f"OK    '{branch}' is allowlisted")
        return 0
    if PATTERN.match(branch):
        print(f"OK    '{branch}' matches the convention")
        return 0

    print(f"FAIL  '{branch}' does not match {PATTERN.pattern}")
    print("        expected <type>/<issue-number>-<kebab-slug>, e.g. feat/42-lanzadera-auth")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
