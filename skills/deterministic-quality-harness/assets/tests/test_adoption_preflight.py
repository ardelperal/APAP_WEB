# HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — assets/tests/test_adoption_preflight.py
"""Adoption tests for the mutation and security assets.

The reference harness must fail before CI when a required lock/config asset is
missing or still contains a placeholder. A copied template is not adopted
until this preflight passes.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ASSETS = Path(__file__).resolve().parent.parent
PREFLIGHT = ASSETS / "scripts" / "check_adoption.py"
if str(PREFLIGHT.parent) not in sys.path:
    sys.path.insert(0, str(PREFLIGHT.parent))
SHA256_A = "a" * 64
SHA256_B = "b" * 64


def _write_adopted_root(root: Path) -> None:
    (root / "quality-policy.json").write_bytes((ASSETS / "quality-policy.json").read_bytes())
    (root / "pyproject.toml").write_text(
        '[tool.coverage.run]\nsource = ["app"]\nomit = []\n', encoding="utf-8"
    )
    (root / "cosmic-ray.toml").write_text(
        '[cosmic-ray]\nmodule-path = "app"\ntimeout = 30.0\n'
        'excluded-modules = []\ntest-command = "python -m pytest -p no:randomly"\n\n'
        '[cosmic-ray.distributor]\nname = "local"\n',
        encoding="utf-8",
    )
    (root / "requirements-dev.lock").write_text(
        f"cosmic-ray==8.7.0 --hash=sha256:{SHA256_A}\n",
        encoding="utf-8",
    )
    sources = {
        "gitleaks": "zricethezav/gitleaks:v8.30.1",
        "trivy": "aquasec/trivy:0.73.0",
    }
    (root / "security-images.sources.json").write_text(
        json.dumps(sources, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    lock = {
        name: {"source": source, "digest": f"sha256:{digest}"}
        for (name, source), digest in zip(
            sorted(sources.items()), (SHA256_A, SHA256_B), strict=True
        )
    }
    (root / "security-images.lock.json").write_text(
        json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(PREFLIGHT), "--root", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
    )


def test_reference_assets_use_one_complete_mutation_contract() -> None:
    workflow = (ASSETS / "ci.yml").read_text(encoding="utf-8")
    makefile = (ASSETS / "Makefile").read_text(encoding="utf-8")
    pyproject = (ASSETS / "pyproject.fragment.toml").read_text(encoding="utf-8")

    assert (ASSETS / "cosmic-ray.toml").is_file()
    assert "cosmic-ray==8.7.0" in pyproject
    assert "cosmic-ray baseline cosmic-ray.toml" in workflow
    assert "cosmic-ray init cosmic-ray.toml mutation-session.sqlite" in workflow
    assert "cosmic-ray baseline cosmic-ray.toml" in makefile
    assert "cosmic-ray init cosmic-ray.toml mutation-session.sqlite" in makefile


def test_reference_assets_have_resolved_scanner_locks_and_a_ci_preflight() -> None:
    workflow = (ASSETS / "ci.yml").read_text(encoding="utf-8")
    lock = json.loads(
        (ASSETS / "security-images.lock.json").read_text(encoding="utf-8")
    )

    assert "REPLACE_WITH_DIGEST" not in workflow
    assert "python scripts/check_adoption.py" in workflow
    assert "--print-image gitleaks" in workflow
    assert "--print-image trivy" in workflow
    assert all(entry["digest"].startswith("sha256:") for entry in lock.values())
    assert all(len(entry["digest"]) == 71 for entry in lock.values())


@pytest.mark.parametrize(
    "missing",
    [
        "cosmic-ray.toml",
        "requirements-dev.lock",
        "security-images.sources.json",
        "security-images.lock.json",
        "quality-policy.json",
        "pyproject.toml",
    ],
)
def test_preflight_rejects_a_missing_required_asset(
    tmp_path: Path, missing: str
) -> None:
    _write_adopted_root(tmp_path)
    (tmp_path / missing).unlink()

    result = _run(tmp_path)

    assert result.returncode == 1
    assert missing in result.stderr


def test_preflight_rejects_placeholder_scanner_digests(tmp_path: Path) -> None:
    _write_adopted_root(tmp_path)
    lock = json.loads(
        (tmp_path / "security-images.lock.json").read_text(encoding="utf-8")
    )
    lock["gitleaks"]["digest"] = "sha256:REPLACE_WITH_DIGEST"
    (tmp_path / "security-images.lock.json").write_text(
        json.dumps(lock), encoding="utf-8"
    )

    result = _run(tmp_path)

    assert result.returncode == 1
    assert "gitleaks" in result.stderr


def test_preflight_rejects_an_unhashed_or_wrong_mutation_pin(tmp_path: Path) -> None:
    _write_adopted_root(tmp_path)
    (tmp_path / "requirements-dev.lock").write_text(
        "cosmic-ray==8.4.6\n", encoding="utf-8"
    )

    result = _run(tmp_path)

    assert result.returncode == 1
    assert "cosmic-ray==8.7.0" in result.stderr


def test_preflight_rejects_mutation_subject_drift_from_quality_policy(tmp_path: Path) -> None:
    _write_adopted_root(tmp_path)
    config = (tmp_path / "cosmic-ray.toml").read_text(encoding="utf-8")
    (tmp_path / "cosmic-ray.toml").write_text(
        config.replace('module-path = "app"', 'module-path = "src"'), encoding="utf-8"
    )

    result = _run(tmp_path)

    assert result.returncode == 1
    assert "quality policy" in result.stderr


def test_preflight_rejects_coverage_subject_drift_from_quality_policy(tmp_path: Path) -> None:
    _write_adopted_root(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[tool.coverage.run]\nsource = ["src"]\nomit = []\n', encoding="utf-8"
    )

    result = _run(tmp_path)

    assert result.returncode == 1
    assert "quality policy" in result.stderr


def test_preflight_accepts_complete_assets_and_prints_locked_images(
    tmp_path: Path,
) -> None:
    _write_adopted_root(tmp_path)

    result = _run(tmp_path)
    image = _run(tmp_path, "--print-image", "gitleaks")

    assert result.returncode == 0, result.stderr
    assert image.returncode == 0, image.stderr
    assert image.stdout.strip() == f"zricethezav/gitleaks:v8.30.1@sha256:{SHA256_A}"


def test_digest_resolution_is_sorted_validated_and_canonical(tmp_path: Path) -> None:
    module_name = "check_adoption"
    spec = __import__("importlib.util").util.spec_from_file_location(
        module_name, PREFLIGHT
    )
    assert spec and spec.loader
    module = __import__("importlib.util").util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    sources = {"trivy": "example/trivy:1", "gitleaks": "example/gitleaks:1"}
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        digest = SHA256_A if "gitleaks" in command[4] else SHA256_B
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps(f"sha256:{digest}"), stderr=""
        )

    resolved = module.resolve_security_images(sources, runner=fake_run)

    assert list(resolved) == ["gitleaks", "trivy"]
    assert [command[4] for command in calls] == [
        "example/gitleaks:1",
        "example/trivy:1",
    ]
    assert resolved["gitleaks"]["digest"] == f"sha256:{SHA256_A}"


@pytest.mark.parametrize(
    "bad_output", ["not-json", '"sha256:short"', '"REPLACE_WITH_DIGEST"']
)
def test_digest_resolution_fails_closed_on_unverifiable_output(bad_output: str) -> None:
    module_name = "check_adoption_invalid"
    spec = __import__("importlib.util").util.spec_from_file_location(
        module_name, PREFLIGHT
    )
    assert spec and spec.loader
    module = __import__("importlib.util").util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout=bad_output, stderr="")

    with pytest.raises(module.AdoptionError):
        module.resolve_security_images(
            {"gitleaks": "example/gitleaks:1"}, runner=fake_run
        )
