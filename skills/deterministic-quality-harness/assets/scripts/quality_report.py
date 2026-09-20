#!/usr/bin/env python3
# HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — assets/scripts/quality_report.py
"""Aggregate every gate's indicator envelope into one report.

Gates answer pass/fail. Indicators answer "by how much, and which way is it moving" — which is
what you need to decide whether to spend a day on cleanup, and what a ratchet's target date is
measured against. This runs each gate in ``--json`` mode, merges the envelopes, writes
``quality-report.json``, and renders a markdown table into the CI step summary.

DETERMINISM: the report carries the commit SHA, never a wall-clock timestamp. Two runs over the
same commit and explicit policy date must produce byte-identical output. A changed date is a
recorded policy evaluation, never hidden wall-clock drift. Gates run in fixed order.

Exit codes:
    0  every gate passed
    1  any gate failed, errored, or produced an unreadable envelope
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from policy_time import add_policy_date_argument
from quality_policy import (
    DEFAULT_POLICY_PATH,
    REQUIRED_GATES,
    PolicyError,
    build_evidence,
    load_policy,
)

# --------------------------------------------------------------------------------------------
# CONFIGURATION
# --------------------------------------------------------------------------------------------

#: Fixed execution order (Hard Rule 13). Cheap and structural first, so the first failure a
#: developer sees is the one that changes the most downstream numbers.
GATES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("layers", "check_layers.py", ()),
    ("complexity", "check_complexity.py", ()),
    ("crap", "check_crap.py", ()),
    ("mutation_sites", "check_mutation_sites.py", ()),
    ("dry", "check_dry.py", ()),
)

#: The mutation gate is not here on purpose: it consumes a session database produced by a real
#: mutation run, which is far too slow for every PR. It runs on a schedule and reports through
#: the same envelope. Its absence from a PR report is expected; a PR report that claimed to
#: include it would be lying.

#: PR-scoped gates. They need a base ref and a PR body, so they only run with --include-pr-gates.
PR_GATES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("branch_name", "check_branch_name.py", ()),
    ("pr_size", "check_pr_size.py", ()),
)

#: PR gates operate on Git/CI context from their working directory and do not accept ``--root``.
ROOTLESS_GATES = frozenset(name for name, _, _ in PR_GATES)

#: The published indicator set: what it means, and which direction is good. Everything here is
#: derived from a gate envelope — this table never computes anything itself.
INDICATOR_MEANINGS: dict[str, tuple[str, str]] = {
    "violations": ("architecture boundary violations", "lower"),
    "violation_classes": ("distinct violation kinds", "lower"),
    "max_complexity": ("highest cyclomatic complexity of any function", "lower"),
    "functions_over_ceiling": ("functions above the gate ceiling", "lower"),
    "functions_measured": ("functions the gate could measure", "higher"),
    "max_crap": ("highest CRAP score of any function", "lower"),
    "line_coverage_pct": ("statements executed by the suite", "higher"),
    "max_mutation_sites": ("largest mutation surface of any file", "lower"),
    "files_over_ceiling": ("files above the gate ceiling", "lower"),
    "total_mutation_sites": ("mutation surface of the whole package", "lower"),
    "mutation_score_pct": ("mutants the suite killed", "higher"),
    "survivors_total": ("mutants no test noticed", "lower"),
    "incompetent_ratio_pct": ("mutants that could not execute; high means a broken run", "lower"),
    "mutants_measured": ("mutants the run actually evaluated", "higher"),
    "duplicate_groups": ("distinct duplicated blocks", "lower"),
    "duplicated_statements": ("statements inside a duplicated block", "lower"),
    "duplicated_ratio_pct": ("duplicated share of all statements", "lower"),
    "changed_lines": ("reviewable lines in this change", "lower"),
    "files_changed": ("files touched by this change", "lower"),
    "overridden": ("review budget explicitly overridden", "lower"),
    "conformant": ("branch name matches the convention", "higher"),
}

# --------------------------------------------------------------------------------------------
# MECHANISM
# --------------------------------------------------------------------------------------------


def _commit(root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _error_envelope(gate: str, detail: str) -> dict:
    return {
        "gate": gate,
        "status": "error",
        "detail": detail.strip()[:500],
        "indicators": {},
        "ceilings": {},
        "findings": [],
    }


def _envelope_error(envelope: object, expected_gate: str) -> str | None:
    if not isinstance(envelope, dict):
        return "gate output must be a JSON object"

    required_types = {
        "gate": str,
        "status": str,
        "indicators": dict,
        "ceilings": dict,
        "findings": list,
    }
    for field, field_type in required_types.items():
        if field not in envelope:
            return f"gate envelope is missing required field '{field}'"
        if not isinstance(envelope[field], field_type):
            return f"gate envelope field '{field}' must be {field_type.__name__}"

    if envelope["gate"] != expected_gate:
        return f"gate identity '{envelope['gate']}' does not match expected '{expected_gate}'"
    if envelope["status"] not in {"pass", "fail", "error"}:
        return "gate envelope status must be one of: pass, fail, error"

    if expected_gate in REQUIRED_GATES:
        binding_types = {
            "candidate": dict,
            "policy_identity": str,
            "scope_identity": str,
            "subject_manifest": list,
            "tool": dict,
            "owner": str,
            "non_ownership": list,
            "subjects": dict,
        }
        for field, field_type in binding_types.items():
            if field not in envelope or not isinstance(envelope[field], field_type):
                return f"gate envelope binding '{field}' must be {field_type.__name__}"

    for index, finding in enumerate(envelope["findings"]):
        if not isinstance(finding, dict):
            return f"finding {index} must be an object"
        for field, field_type in {"file": str, "line": int, "detail": str}.items():
            if field not in finding or not isinstance(finding[field], field_type):
                return f"finding {index} field '{field}' must be {field_type.__name__}"
    return None


def run_gate(
    expected_gate: str, scripts: Path, script: str, root: Path, extra: tuple[str, ...]
) -> dict:
    command = [sys.executable, str(scripts / script)]
    if expected_gate not in ROOTLESS_GATES:
        command.extend(("--root", str(root)))
    command.extend(("--json", *extra))
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        cwd=root,
    )
    try:
        envelope = json.loads(result.stdout)
    except json.JSONDecodeError:
        return _error_envelope(expected_gate, result.stderr or result.stdout or "no output")

    validation_error = _envelope_error(envelope, expected_gate)
    if validation_error:
        return _error_envelope(expected_gate, validation_error)

    process_passed = result.returncode == 0
    envelope_passed = envelope["status"] == "pass"
    if process_passed != envelope_passed:
        return _error_envelope(
            expected_gate,
            f"process exit code {result.returncode} disagrees with envelope status "
            f"'{envelope['status']}'",
        )
    return envelope


def build_report(root: Path, envelopes: list[dict], policy_date: str) -> dict:
    report_evidence: dict = {}
    try:
        policy = load_policy(DEFAULT_POLICY_PATH)
    except PolicyError as exc:
        policy = None
        for envelope in envelopes:
            if envelope.get("gate") in REQUIRED_GATES:
                envelope["status"] = "error"
                envelope["detail"] = str(exc)

    if policy is not None:
        for envelope in envelopes:
            gate = envelope.get("gate")
            if gate not in REQUIRED_GATES or envelope.get("status") == "error":
                continue
            try:
                expected = build_evidence(root, policy, gate)
            except PolicyError as exc:
                envelope["status"] = "error"
                envelope["detail"] = str(exc)
                continue
            if not report_evidence:
                report_evidence = {
                    field: expected[field]
                    for field in (
                        "candidate",
                        "policy_identity",
                        "scope_identity",
                        "subject_manifest",
                    )
                }
            if envelope.get("candidate") != expected["candidate"]:
                envelope["status"] = "error"
                envelope["detail"] = "candidate identity mismatch"
            elif envelope.get("subject_manifest") != expected["subject_manifest"]:
                envelope["status"] = "error"
                envelope["detail"] = "scope identity no longer matches current subjects"
            elif envelope.get("policy_identity") != expected["policy_identity"]:
                envelope["status"] = "error"
                envelope["detail"] = "policy identity mismatch"
            elif envelope.get("scope_identity") != expected["scope_identity"]:
                envelope["status"] = "error"
                envelope["detail"] = "scope identity mismatch"
            elif envelope.get("tool") != expected["tool"]:
                envelope["status"] = "error"
                envelope["detail"] = "tool identity mismatch"

    indicators: dict[str, dict] = {}
    for envelope in envelopes:
        gate = envelope.get("gate", "unknown")
        ceilings = envelope.get("ceilings", {})
        for name, value in sorted(envelope.get("indicators", {}).items()):
            meaning, direction = INDICATOR_MEANINGS.get(name, (name, "lower"))
            indicators[f"{gate}.{name}"] = {
                "value": value,
                "ceiling": ceilings.get(name),
                "direction": direction,
                "meaning": meaning,
            }
    failed = [
        envelope.get("gate", "unknown")
        for envelope in envelopes
        if envelope.get("status") != "pass"
    ]
    report = {
        "schema": "deterministic-quality-harness/quality-report/v1",
        # Commit, never a timestamp: the same commit must always produce the same report.
        "commit": _commit(root),
        "policy_date": policy_date,
        "status": "pass" if not failed else "fail",
        "failed_gates": sorted(failed),
        "indicators": indicators,
        "gates": envelopes,
    }
    report.update(report_evidence)
    return report


def render_markdown(report: dict) -> str:
    icon = "PASS" if report["status"] == "pass" else "FAIL"
    lines = [
        f"## Quality indicators — {icon}",
        "",
        f"Commit `{report['commit'][:12]}`",
        f"Policy date `{report['policy_date']}`",
        "",
        "| Indicator | Value | Ceiling | Good direction | Meaning |",
        "|---|---:|---:|---|---|",
    ]
    for name, entry in report["indicators"].items():
        ceiling = "—" if entry["ceiling"] is None else entry["ceiling"]
        lines.append(
            f"| `{name}` | {entry['value']} | {ceiling} | {entry['direction']} | "
            f"{entry['meaning']} |"
        )

    failing = [envelope for envelope in report["gates"] if envelope.get("status") != "pass"]
    if failing:
        lines += ["", "### Failing gates", ""]
        for envelope in failing:
            gate = envelope.get("gate", "unknown")
            detail = envelope.get("detail")
            lines.append(f"**{gate}** — {envelope.get('status')}" + (f": {detail}" if detail else ""))
            for finding in envelope.get("findings", [])[:20]:
                lines.append(f"- `{finding['file']}:{finding['line']}` {finding['detail']}")
            lines.append("")
    return "\n".join(lines) + "\n"


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
    add_policy_date_argument(parser)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    parser.add_argument(
        "--scripts",
        type=Path,
        default=None,
        help="directory holding the gate scripts (default: alongside this file)",
    )
    parser.add_argument(
        "--out", type=Path, default=None, help="report path (default: <root>/quality-report.json)"
    )
    parser.add_argument(
        "--include-pr-gates",
        action="store_true",
        help="also run the PR-scoped gates (branch name, PR size)",
    )
    args = parser.parse_args(argv)

    root = args.root.resolve()
    scripts = (args.scripts or Path(__file__).resolve().parent).resolve()
    out = args.out or (root / "quality-report.json")

    policy_args = ("--policy-date", args.policy_date.isoformat())
    selected = [(name, script, extra + policy_args) for name, script, extra in GATES]
    if args.include_pr_gates:
        selected += list(PR_GATES)
    envelopes = [
        run_gate(gate, scripts, script, root, extra) for gate, script, extra in selected
    ]
    report = build_report(root, envelopes, args.policy_date.isoformat())

    out.write_text(json.dumps(report, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    markdown = render_markdown(report)
    print(markdown, end="")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(markdown)

    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
