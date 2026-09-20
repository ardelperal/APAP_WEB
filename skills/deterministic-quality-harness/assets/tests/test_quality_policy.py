# HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — assets/tests/test_quality_policy.py
"""Contract tests for the shared quality-policy evidence boundary."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def _load_quality_policy():
    name = "quality_policy_contract_subject"
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / "quality_policy.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _write_subjects(root: Path) -> None:
    (root / "app" / "pkg" / "migrations").mkdir(parents=True)
    (root / "app" / "pkg" / "b.py").write_text("B = 2\n", encoding="utf-8")
    (root / "app" / "pkg" / "a.py").write_text("A = 1\n", encoding="utf-8")
    (root / "app" / "pkg" / "migrations" / "ignored.py").write_text(
        "IGNORED = True\n", encoding="utf-8"
    )


def test_policy_builds_an_ordered_content_bound_manifest(tmp_path) -> None:
    module = _load_quality_policy()
    _write_subjects(tmp_path)

    policy = module.load_policy(ROOT / "quality-policy.json")
    first = module.build_evidence(tmp_path, policy, "complexity")
    second = module.build_evidence(tmp_path, policy, "complexity")

    assert [item["path"] for item in first["subject_manifest"]] == [
        "app/pkg/a.py",
        "app/pkg/b.py",
    ]
    assert first == second
    assert first["candidate"]["tree"]
    assert first["scope_identity"].startswith("sha256:")
    assert first["tool"]["command"] == ["python", "scripts/check_complexity.py"]
    assert first["owner"] == "quality-architecture"
    assert first["non_ownership"]


def test_policy_rejects_a_gate_without_explicit_non_ownership(tmp_path) -> None:
    module = _load_quality_policy()
    payload = json.loads((ROOT / "quality-policy.json").read_text(encoding="utf-8"))
    del payload["gates"]["complexity"]["non_ownership"]
    policy_path = tmp_path / "quality-policy.json"
    policy_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(module.PolicyError, match="non_ownership"):
        module.load_policy(policy_path)


def test_policy_rejects_an_empty_subject_denominator(tmp_path) -> None:
    module = _load_quality_policy()
    policy = module.load_policy(ROOT / "quality-policy.json")

    with pytest.raises(module.PolicyError, match="no eligible subjects"):
        module.build_evidence(tmp_path, policy, "layers")


def test_scope_identity_changes_when_subject_content_changes(tmp_path) -> None:
    module = _load_quality_policy()
    _write_subjects(tmp_path)
    policy = module.load_policy(ROOT / "quality-policy.json")
    before = module.build_evidence(tmp_path, policy, "dry")

    (tmp_path / "app" / "pkg" / "a.py").write_text("A = 99\n", encoding="utf-8")
    after = module.build_evidence(tmp_path, policy, "dry")

    assert before["candidate"] == after["candidate"]
    assert before["subject_manifest"] != after["subject_manifest"]
    assert before["scope_identity"] != after["scope_identity"]
