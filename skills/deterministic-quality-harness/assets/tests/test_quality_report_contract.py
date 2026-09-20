# HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — assets/tests/test_quality_report_contract.py
"""Contract tests for the quality-report subprocess boundary."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def _load_quality_report():
    name = "quality_report_contract_subject"
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / "quality_report.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _pass_envelope(gate: str = "layers") -> dict:
    return {
        "gate": gate,
        "status": "pass",
        "indicators": {},
        "ceilings": {},
        "findings": [],
    }


def _bound_envelope(module, root: Path, gate: str = "layers") -> dict:
    policy = module.load_policy(module.DEFAULT_POLICY_PATH)
    envelope = _pass_envelope(gate)
    envelope.update(module.build_evidence(root, policy, gate))
    envelope["subjects"] = {
        "checked": [item["path"] for item in envelope["subject_manifest"]],
        "skipped": [],
        "unclassified": [],
    }
    return envelope


def _completed(envelope: object, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["gate"], returncode=returncode, stdout=json.dumps(envelope), stderr=""
    )


@pytest.mark.parametrize(
    ("returncode", "status"),
    [(1, "pass"), (0, "fail")],
)
def test_run_gate_rejects_exit_code_status_disagreement(
    monkeypatch, tmp_path, returncode: int, status: str
) -> None:
    module = _load_quality_report()
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "subject.py").write_text("VALUE = 1\n", encoding="utf-8")
    envelope = _bound_envelope(module, tmp_path)
    envelope["status"] = status
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: _completed(envelope, returncode),
    )

    result = module.run_gate("layers", SCRIPTS, "check_layers.py", tmp_path, ())

    assert result["gate"] == "layers"
    assert result["status"] == "error"
    assert f"exit code {returncode}" in result["detail"]


def test_run_gate_rejects_invalid_json(monkeypatch, tmp_path) -> None:
    module = _load_quality_report()
    invalid = subprocess.CompletedProcess(args=["gate"], returncode=0, stdout="{", stderr="")
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: invalid)

    result = module.run_gate("layers", SCRIPTS, "check_layers.py", tmp_path, ())

    assert result["gate"] == "layers"
    assert result["status"] == "error"


@pytest.mark.parametrize(
    "envelope",
    [
        {},
        {"gate": "layers", "status": "pass", "indicators": {}, "findings": []},
        {
            "gate": "layers",
            "status": "pass",
            "indicators": [],
            "ceilings": {},
            "findings": [],
        },
    ],
)
def test_run_gate_rejects_malformed_or_incomplete_envelope(
    monkeypatch, tmp_path, envelope: dict
) -> None:
    module = _load_quality_report()
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: _completed(envelope))

    result = module.run_gate("layers", SCRIPTS, "check_layers.py", tmp_path, ())

    assert result["gate"] == "layers"
    assert result["status"] == "error"


def test_run_gate_rejects_wrong_gate_identity(monkeypatch, tmp_path) -> None:
    module = _load_quality_report()
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: _completed(_pass_envelope("complexity")),
    )

    result = module.run_gate("layers", SCRIPTS, "check_layers.py", tmp_path, ())

    assert result["gate"] == "layers"
    assert result["status"] == "error"
    assert "expected 'layers'" in result["detail"]


def test_build_report_rejects_candidate_identity_mismatch(tmp_path) -> None:
    module = _load_quality_report()
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "subject.py").write_text("VALUE = 1\n", encoding="utf-8")
    first = _bound_envelope(module, tmp_path, "layers")
    second = _bound_envelope(module, tmp_path, "complexity")
    second["candidate"] = {"commit": "other", "tree": "other"}

    report = module.build_report(tmp_path, [first, second], "2026-08-12")

    assert report["status"] == "fail"
    assert report["failed_gates"] == ["complexity"]
    assert "candidate identity mismatch" in second["detail"]


def test_build_report_rejects_scope_identity_mismatch(tmp_path) -> None:
    module = _load_quality_report()
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "subject.py").write_text("VALUE = 1\n", encoding="utf-8")
    first = _bound_envelope(module, tmp_path, "layers")
    second = _bound_envelope(module, tmp_path, "complexity")
    second["scope_identity"] = "sha256:stale"

    report = module.build_report(tmp_path, [first, second], "2026-08-12")

    assert report["status"] == "fail"
    assert "scope identity mismatch" in second["detail"]


def test_build_report_rejects_tool_identity_mismatch(tmp_path) -> None:
    module = _load_quality_report()
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "subject.py").write_text("VALUE = 1\n", encoding="utf-8")
    envelope = _bound_envelope(module, tmp_path, "layers")
    envelope["tool"]["sha256"] = "stale"

    report = module.build_report(tmp_path, [envelope], "2026-08-12")

    assert report["status"] == "fail"
    assert "tool identity mismatch" in envelope["detail"]


def test_build_report_rejects_reused_evidence_after_subject_change(tmp_path) -> None:
    module = _load_quality_report()
    (tmp_path / "app").mkdir()
    subject = tmp_path / "app" / "subject.py"
    subject.write_text("VALUE = 1\n", encoding="utf-8")
    stale = _bound_envelope(module, tmp_path, "layers")
    subject.write_text("VALUE = 2\n", encoding="utf-8")

    report = module.build_report(tmp_path, [stale], "2026-08-12")

    assert report["status"] == "fail"
    assert "scope identity no longer matches" in stale["detail"]


def _git(root: Path, *args: str) -> None:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr


def test_include_pr_gates_executes_with_valid_inputs(monkeypatch, tmp_path) -> None:
    module = _load_quality_report()
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Harness Test")
    _git(repo, "config", "user.email", "harness@example.invalid")
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "test: seed fixture")
    monkeypatch.setenv("BRANCH_NAME", "fix/15-aggregator-contract")
    monkeypatch.setenv("BASE_REF", "main")
    monkeypatch.setattr(module, "GATES", ())

    result = module.main(
        [
            "--root",
            str(repo),
            "--scripts",
            str(SCRIPTS),
            "--out",
            str(repo / "quality-report.json"),
            "--policy-date",
            "2026-08-12",
            "--include-pr-gates",
        ]
    )

    assert result == 0
    report = json.loads((repo / "quality-report.json").read_text(encoding="utf-8"))
    assert [gate["gate"] for gate in report["gates"]] == ["branch_name", "pr_size"]
    assert all(gate["status"] == "pass" for gate in report["gates"])
