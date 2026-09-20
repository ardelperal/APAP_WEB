# HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — assets/tests/test_gate_liveness.py
"""Adversarial liveness tests for gates that walk source trees.

An existing package directory is not proof that a gate inspected anything. These tests pin the
stronger contract: every tree-walking gate must find at least one eligible subject or fail with a
machine-readable error and a zero-valued liveness indicator.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
EMPTY_SUBJECTS = Path(__file__).resolve().parent / "fixtures" / "empty_subjects"


def _run_json(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable, str(SCRIPTS / script), "--root", str(EMPTY_SUBJECTS),
            "--policy-date", "2026-08-12", "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("script", "gate", "indicator"),
    [
        ("check_complexity.py", "complexity", "functions_measured"),
        ("check_layers.py", "layers", "files_checked"),
        ("check_dry.py", "dry", "statements_measured"),
        ("check_mutation_sites.py", "mutation_sites", "files_measured"),
    ],
)
def test_tree_gate_fails_closed_when_no_eligible_subject_exists(
    script: str, gate: str, indicator: str
) -> None:
    result = _run_json(script)

    assert result.returncode == 1, result.stdout
    envelope = json.loads(result.stdout)
    assert envelope["gate"] == gate
    assert envelope["status"] == "error"
    assert envelope["indicators"][indicator] == 0
    assert envelope["candidate"]["tree"]
    assert envelope["scope_identity"].startswith("sha256:")
    assert envelope["subject_manifest"] == []
    assert envelope["subjects"] == {"checked": [], "skipped": [], "unclassified": []}
    assert "no eligible" in envelope["detail"]
