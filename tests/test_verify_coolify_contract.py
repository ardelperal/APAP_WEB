"""Tests for the isolated Coolify deploy contract verifier.

The verifier is part of the release-side CI/CD reform (Gap 3): it
mirrors gentle-ai's ``internal/releasepolicy/policy.go`` pattern of an
isolated module with the canonical contract embedded so it cannot
depend on the tree it validates. These tests pin the verifier's
behavior across the happy path, every documented drift, the
file-missing failure mode, and the GitHub Actions error annotation
contract.

The fixture copies the shipped ``coolify/apap-web-coolify.yaml`` (which
must match the canonical exactly — that is the very contract this
slice introduces) and mutates one field per test so each case is a
single, named edit on a known-good baseline. That keeps the tests
self-contained: no import gymnastics, no source-file regexes, no
duplicate canonical in the test file.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "verify_coolify_contract.py"
YAML_PATH = REPO_ROOT / "coolify" / "apap-web-coolify.yaml"


@pytest.fixture
def tmp_yaml(tmp_path: Path) -> Path:
    """A tmp copy of the shipped config that individual tests can mutate."""
    target = tmp_path / "coolify.yaml"
    target.write_text(YAML_PATH.read_text(encoding="utf-8"))
    return target


def _mutate(yaml_text: str, old: str, new: str) -> str:
    """Replace exactly one occurrence of ``old`` with ``new``."""
    assert old in yaml_text, f"fixture must contain {old!r}"
    return yaml_text.replace(old, new, 1)


def _run_cli(yaml_path: Path) -> subprocess.CompletedProcess[str]:
    """Invoke the verifier as a subprocess against ``yaml_path``."""
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(yaml_path)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_shipped_config_matches_canonical() -> None:
    """The shipped Coolify config must match the embedded canonical exactly.

    If this test fails, either:
      - someone changed ``coolify/apap-web-coolify.yaml`` without
        updating the canonical in ``scripts/verify_coolify_contract.py``
        (revert the contract change and bring the canonical up to date
        in the same PR), or
      - someone changed the canonical without updating the contract
        (revert the canonical change).
    """
    result = _run_cli(YAML_PATH)
    assert result.returncode == 0, (
        f"verifier exited {result.returncode} against the shipped config; "
        f"stdout={result.stdout!r}, stderr={result.stderr!r}"
    )


def test_wrong_service_name_fails(tmp_yaml: Path) -> None:
    """A drift in ``service.name`` must surface as exit code 1."""
    text = _mutate(tmp_yaml.read_text(encoding="utf-8"), "name: apap-web", "name: wrong")
    tmp_yaml.write_text(text, encoding="utf-8")
    result = _run_cli(tmp_yaml)
    assert result.returncode == 1


def test_wrong_port_fails(tmp_yaml: Path) -> None:
    """A drift in ``service.port`` must surface as exit code 1."""
    text = _mutate(tmp_yaml.read_text(encoding="utf-8"), "port: 8000", "port: 9000")
    tmp_yaml.write_text(text, encoding="utf-8")
    result = _run_cli(tmp_yaml)
    assert result.returncode == 1


def test_wrong_healthcheck_path_fails(tmp_yaml: Path) -> None:
    """A drift in ``healthcheck.path`` must surface as exit code 1."""
    text = _mutate(
        tmp_yaml.read_text(encoding="utf-8"), "path: /healthz", "path: /wrong"
    )
    tmp_yaml.write_text(text, encoding="utf-8")
    result = _run_cli(tmp_yaml)
    assert result.returncode == 1


def test_missing_required_env_var_fails(tmp_yaml: Path) -> None:
    """Removing a required ``APAP_*`` env var must surface as exit code 1."""
    text = tmp_yaml.read_text(encoding="utf-8")
    text = "\n".join(
        line for line in text.splitlines() if "APAP_SESSION_SECRET" not in line
    )
    tmp_yaml.write_text(text + "\n", encoding="utf-8")
    result = _run_cli(tmp_yaml)
    assert result.returncode == 1


def test_extra_unexpected_env_var_fails(tmp_yaml: Path) -> None:
    """Adding an env var not in the canonical must surface as exit code 1."""
    text = tmp_yaml.read_text(encoding="utf-8")
    # Insert the extra entry immediately before ``runbook:`` so it lives
    # INSIDE the env list at the right indent. Appending to the end of the
    # file would land AFTER ``runbook:`` and break the YAML mapping.
    text = text.replace(
        "  runbook:",
        "    - name: APAP_EXTRA_VAR\n      value: \"surprise\"\n  runbook:",
        1,
    )
    tmp_yaml.write_text(text, encoding="utf-8")
    result = _run_cli(tmp_yaml)
    assert result.returncode == 1


def test_missing_config_file_fails(tmp_path: Path) -> None:
    """A non-existent config path must surface as exit code 2."""
    result = _run_cli(tmp_path / "does-not-exist.yaml")
    assert result.returncode == 2


def test_failure_emits_github_error_annotations(tmp_yaml: Path) -> None:
    """Failures must surface as ``::error::`` annotations on stderr.

    GitHub Actions only picks up ``::error::`` markers from stderr,
    not stdout — a verifier that wrote its diffs to stdout would
    silently fail in CI even though the subprocess exit code was 1.
    """
    text = _mutate(tmp_yaml.read_text(encoding="utf-8"), "port: 8000", "port: 9000")
    tmp_yaml.write_text(text, encoding="utf-8")
    result = _run_cli(tmp_yaml)
    assert "::error::" in result.stderr, (
        f"missing GitHub Actions error annotation; stderr={result.stderr!r}"
    )


def test_malformed_yaml_surfaces_as_exit_2(tmp_yaml: Path) -> None:
    """A YAML parse error must surface as exit code 2 (file error), not 1."""
    tmp_yaml.write_text("service:\n  name: : : unterminated\n", encoding="utf-8")
    result = _run_cli(tmp_yaml)
    assert result.returncode == 2


def test_top_level_non_mapping_surfaces_as_exit_1(tmp_yaml: Path) -> None:
    """A top-level non-mapping (list/scalar) must surface as exit code 1."""
    tmp_yaml.write_text("- just a list\n- no service key\n", encoding="utf-8")
    result = _run_cli(tmp_yaml)
    assert result.returncode == 1
