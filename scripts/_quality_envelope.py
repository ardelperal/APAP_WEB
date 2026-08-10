"""Shared envelope schema for per-gate indicator emission.

Per ``deterministic-quality-harness`` v1.5 Rule 16: "Every gate publishes
an indicator, not only a verdict. Each gate emits a machine-readable
envelope (gate, status, indicators, ceilings, findings); one aggregator
merges them into a single report and renders it where reviewers already
look."

The envelope shape is a JSON object with these fields:

  ``gate``         (str)         Gate identifier (e.g. ``"module_size"``).
  ``status``       (str)         ``"pass"`` or ``"fail"``.
  ``indicators``   (dict)        Measured values. Keys are stable.
  ``ceilings``     (dict)        Absolute maxima for ``lower is better``
                               indicators. Empty for ``higher is better``
                               gates (the ceiling is implicit at 100,
                               e.g. coverage).
  ``findings``     (list[dict])  Per-finding rows with ``file``, ``line``,
                               ``detail``. Empty when the gate is clean.

The aggregator (``scripts/quality_report.py``) reads every
``quality/<gate>.json`` and renders the standard table the skill's
section "Indicators" describes.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path


def now_iso() -> str:
    """Return the current UTC time in ISO 8601 with second precision."""
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def write_envelope(
    out_path: Path,
    gate: str,
    status: str,
    indicators: dict,
    ceilings: dict,
    findings: list[dict],
) -> None:
    """Write a single gate's envelope to ``out_path`` as UTF-8 JSON.

    Side effects:
    - Creates ``out_path.parent`` if missing.
    - Overwrites ``out_path`` if it exists.
    - Pins the encoding to UTF-8 (deterministic output per Rule 17).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    envelope = {
        "schema_version": 1,
        "emitted_at": now_iso(),
        "gate": gate,
        "status": status,
        "indicators": dict(sorted(indicators.items())),
        "ceilings": dict(sorted(ceilings.items())),
        "findings": findings,
    }
    out_path.write_text(
        json.dumps(envelope, indent=2, sort_keys=False, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _read_envelope(path: Path) -> dict | None:
    """Read an envelope from ``path``. Returns None on missing or malformed JSON."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    if data.get("schema_version") != 1:
        return None  # future schema; let the aggregator decide what to do
    return data


def load_envelopes(quality_dir: Path) -> dict[str, dict]:
    """Load every ``<gate>.json`` under ``quality_dir``.

    Returns ``{gate_name: envelope}``. Missing files and malformed JSON are
    silently skipped — the aggregator decides what to do with a missing gate
    (currently: report as not yet migrated).
    """
    out: dict[str, dict] = {}
    if not quality_dir.is_dir():
        return out
    for path in sorted(quality_dir.glob("*.json")):
        env = _read_envelope(path)
        if env is None:
            continue
        gate = env.get("gate") or path.stem
        out[gate] = env
    return out


def emit_envelope_argparse_action(argparser):
    """Attach ``--emit-envelope <path>`` to an existing ``argparse`` parser.

    Returns the action so callers can fetch the value with
    ``args.emit_envelope``. When the flag is absent the value is ``None``
    and the gate runs as before (verdict-only output).
    """
    argparser.add_argument(
        "--emit-envelope",
        type=Path,
        default=None,
        metavar="PATH",
        help="Also write the indicator envelope (Rule 16) to PATH as UTF-8 JSON.",
    )
    return argparser


def _pin_output_encoding() -> None:
    """Pin stdout/stderr to UTF-8 (Rule 17)."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")


__all__ = [
    "now_iso",
    "write_envelope",
    "load_envelopes",
    "emit_envelope_argparse_action",
    "_pin_output_encoding",
]
