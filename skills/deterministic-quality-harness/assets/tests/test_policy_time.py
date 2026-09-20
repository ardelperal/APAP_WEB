# HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — assets/tests/test_policy_time.py
"""The wall clock is an orchestration input, never hidden gate state."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ASSETS = Path(__file__).resolve().parent.parent
SCRIPTS = ASSETS / "scripts"


def _load(name: str):
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_policy_date_parser_accepts_only_iso_calendar_dates() -> None:
    module = _load("policy_time")

    assert module.parse_policy_date("2026-08-12").isoformat() == "2026-08-12"
    for invalid in ("", "2026-8-12", "12/08/2026", "2026-02-30"):
        with pytest.raises(module.PolicyTimeError):
            module.parse_policy_date(invalid)


def test_ratchet_gates_never_read_the_wall_clock_implicitly() -> None:
    ratchet_scripts = (
        "check_complexity.py",
        "check_crap.py",
        "check_dry.py",
        "check_layers.py",
        "check_mutation.py",
        "check_mutation_sites.py",
    )

    for name in ratchet_scripts:
        source = (SCRIPTS / name).read_text(encoding="utf-8")
        assert "date.today()" not in source, name
        assert "add_policy_date_argument(parser)" in source, name


def test_quality_report_records_policy_date_as_evidence() -> None:
    module = _load("quality_report")
    report = module.build_report(Path.cwd(), [], "2026-08-12")

    assert report["policy_date"] == "2026-08-12"
