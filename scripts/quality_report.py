"""Aggregate every per-gate indicator envelope into a single report.

Per ``deterministic-quality-harness`` v1.5 Rule 16: "one aggregator
merges them into a single report and renders it where reviewers
already look." The output is a Markdown table intended for the
GitHub Actions step summary, where reviewers see it on every PR.

Usage::

    python scripts/quality_report.py [quality_dir]

``quality_dir`` defaults to ``quality/`` at the repo root. Each file
``<gate>.json`` in that directory is one gate's envelope. Missing or
malformed files are reported as ``[not-migrated]`` so a follow-up
slice can migrate the remaining gates without breaking CI.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from _quality_envelope import _pin_output_encoding, load_envelopes

#: Indicator to a friendly name + good direction. The aggregator renders
#: these as columns in the report table. Gates not listed here are still
#: reported but with ``direction: ?`` so a missing entry is visible.
INDICATOR_LABELS: dict[str, tuple[str, str]] = {
    # Key format: gate name + indicator name. Value: column label and good direction.
    ("module_size", "files_in_baseline"): ("module_size: files in BASELINE", "lower"),
    ("module_size", "files_over_budget"): ("module_size: files over budget (no BASELINE)", "lower"),
}


def _label(gate: str, indicator: str) -> tuple[str, str]:
    """Return (column_label, good_direction) for a (gate, indicator) pair."""
    return INDICATOR_LABELS.get(
        (gate, indicator),
        (f"{gate}.{indicator}", "?"),
    )


def _status_emoji(status: str) -> str:
    return {"pass": "✅", "fail": "❌"}.get(status, "❔")


def render_markdown(envelopes: dict[str, dict]) -> str:
    """Render the aggregated indicator table as Markdown."""
    if not envelopes:
        return (
            "# Quality report\n\n"
            "_No gate envelopes found. Run the gates with `--emit-envelope` "
            "to populate `quality/`._\n"
        )

    lines: list[str] = ["# Quality report", ""]
    lines.append(
        f"_{len(envelopes)} gate(s) reported. "
        "Each row is one indicator. Ceiling column shows the absolute target "
        "for `lower is better` indicators; empty for `higher is better`._"
    )
    lines.append("")

    # Per-gate summary table (one row per gate).
    lines.append("## Gate summary")
    lines.append("")
    lines.append("| Gate | Status | Indicators | Findings |")
    lines.append("|---|---|---:|---:|")
    for gate, env in envelopes.items():
        status = env.get("status", "?")
        indicators = env.get("indicators", {})
        findings = env.get("findings", [])
        indicator_summary = ", ".join(f"`{k}`={v}" for k, v in indicators.items())
        lines.append(
            f"| `{gate}` | {_status_emoji(status)} {status} | {indicator_summary} | {len(findings)} |"
        )
    lines.append("")

    # Per-indicator detail table.
    lines.append("## Indicators")
    lines.append("")
    lines.append("| Gate | Indicator | Value | Ceiling | Good direction |")
    lines.append("|---|---|---:|---:|---|")
    for gate, env in envelopes.items():
        indicators = env.get("indicators", {})
        ceilings = env.get("ceilings", {})
        for ind, value in indicators.items():
            label, direction = _label(gate, ind)
            ceiling = ceilings.get(ind)
            ceiling_str = "—" if ceiling is None else f"{ceiling}"
            lines.append(
                f"| `{gate}` | `{ind}` | {value} | {ceiling_str} | {direction} |"
            )
    lines.append("")

    # Findings detail (only when there are any).
    any_findings = any(env.get("findings") for env in envelopes.values())
    if any_findings:
        lines.append("## Findings")
        lines.append("")
        lines.append("| Gate | File | Line | Detail |")
        lines.append("|---|---|---:|---|")
        for gate, env in envelopes.items():
            for finding in env.get("findings", []):
                lines.append(
                    f"| `{gate}` | `{finding.get('file', '?')}` | "
                    f"{finding.get('line', '?')} | {finding.get('detail', '')} |"
                )
        lines.append("")

    # Status footer.
    failed = [g for g, e in envelopes.items() if e.get("status") != "pass"]
    if failed:
        lines.append(f"**FAIL**: {len(failed)} gate(s) failed: {', '.join(failed)}")
    else:
        lines.append(f"**OK**: all {len(envelopes)} gate(s) passed.")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    _pin_output_encoding()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "quality_dir",
        nargs="?",
        type=Path,
        default=None,
        help="Directory containing per-gate <gate>.json envelopes (default: <repo>/quality).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when any gate envelope is missing or any gate is not migrating.",
    )
    args = parser.parse_args(argv)

    quality_dir = args.quality_dir
    if quality_dir is None:
        quality_dir = Path(__file__).resolve().parents[1] / "quality"

    envelopes = load_envelopes(quality_dir)

    if args.strict and not envelopes:
        print(f"FAIL quality_report: no envelopes found under {quality_dir}", file=sys.stderr)
        return 1

    markdown = render_markdown(envelopes)
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
