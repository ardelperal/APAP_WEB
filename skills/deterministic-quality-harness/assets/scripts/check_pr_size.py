#!/usr/bin/env python3
# HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — assets/scripts/check_pr_size.py
"""PR size gate: a review budget, enforced.

Counts semantic changed lines between the merge base and HEAD. Line-ending churn is not a change
a reviewer has to read, so ``--ignore-cr-at-eol`` normalises CRLF before counting.

The override is deliberately awkward. ``size:exception`` alone does nothing; it must be paired
with a reason line, because an override nobody has to justify is not an override, it is the
default.

Exit codes:
    0  within budget, or overridden with a stated reason
    1  over budget, or overridden without a reason
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

MAX_CHANGED_LINES = 400

#: Generated files a human never reads line by line. Every entry weakens the gate, so keep the
#: list short and justify additions in review.
EXCLUDED_SUFFIXES = ("uv.lock", "poetry.lock", "package-lock.json", "pnpm-lock.yaml")

OVERRIDE_MARKER = "size:exception"
OVERRIDE_REASON = re.compile(r"^\s*size-exception-reason:\s*(?P<reason>\S.*)$", re.MULTILINE)

# --------------------------------------------------------------------------------------------
# MECHANISM
# --------------------------------------------------------------------------------------------


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], capture_output=True, text=True, check=False, encoding="utf-8"
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def changed_lines(base_ref: str) -> tuple[int, list[tuple[str, int]]]:
    """Return the total counted lines and the per-file breakdown, largest first."""
    raw = _git("diff", "--numstat", "--ignore-cr-at-eol", f"{base_ref}...HEAD")
    per_file: list[tuple[str, int]] = []
    total = 0
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added, deleted, path = parts
        if added == "-" or deleted == "-":  # binary file, not reviewable line by line
            continue
        if path.endswith(EXCLUDED_SUFFIXES):
            continue
        count = int(added) + int(deleted)
        total += count
        per_file.append((path, count))
    per_file.sort(key=lambda item: item[1], reverse=True)
    return total, per_file


def override_reason(pr_body: str) -> str | None:
    """Return the stated reason when a valid override is present, else ``None``."""
    if OVERRIDE_MARKER not in pr_body:
        return None
    match = OVERRIDE_REASON.search(pr_body)
    return match.group("reason").strip() if match else None


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
    parser.add_argument(
        "--base-ref",
        default=os.environ.get("BASE_REF", "origin/main"),
        help="ref to diff against (default: $BASE_REF or origin/main)",
    )
    parser.add_argument("--json", action="store_true", help="emit the indicator envelope")
    args = parser.parse_args(argv)

    try:
        total, per_file = changed_lines(args.base_ref)
    except RuntimeError as exc:
        if args.json:
            print(json.dumps({"gate": "pr_size", "status": "error", "detail": str(exc)}))
        else:
            print(f"FAIL  {exc}", file=sys.stderr)
        return 1

    if args.json:
        reason = override_reason(os.environ.get("PR_BODY", ""))
        passed = total <= MAX_CHANGED_LINES or bool(reason)
        print(
            json.dumps(
                {
                    "gate": "pr_size",
                    "status": "pass" if passed else "fail",
                    "indicators": {
                        "changed_lines": total,
                        "files_changed": len(per_file),
                        "overridden": bool(reason),
                    },
                    "ceilings": {"changed_lines": MAX_CHANGED_LINES},
                    "findings": [
                        {"file": path, "line": 0, "detail": f"{count} changed line(s)"}
                        for path, count in per_file[:10]
                    ]
                    if not passed
                    else [],
                },
                indent=2,
            )
        )
        return 0 if passed else 1

    if total <= MAX_CHANGED_LINES:
        print(f"OK    {total} changed line(s), budget is {MAX_CHANGED_LINES}")
        return 0

    pr_body = os.environ.get("PR_BODY", "")
    reason = override_reason(pr_body)
    if reason:
        print(f"OK    {total} changed line(s) over budget, overridden: {reason}")
        return 0

    print(f"FAIL  {total} changed line(s), budget is {MAX_CHANGED_LINES}")
    for path, count in per_file[:10]:
        print(f"        {count:>6}  {path}")
    if OVERRIDE_MARKER in pr_body:
        print(
            f"        '{OVERRIDE_MARKER}' found but no 'size-exception-reason: <why>' line in the "
            f"PR body"
        )
    else:
        print(
            f"        split the PR, or add '{OVERRIDE_MARKER}' plus a "
            f"'size-exception-reason: <why>' line to the PR body"
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
