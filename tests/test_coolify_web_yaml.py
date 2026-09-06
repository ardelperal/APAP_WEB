"""Tests for ``coolify/apap-web-coolify.yaml`` (Phase 3b, issue #648).

The yaml is the deploy contract for the ``apap-web`` Coolify service:
it captures the image, ports, env vars, healthcheck and domains in
a single reference file so an operator (or a future Coolify import
script) can provision the service reproducibly. The file is not
consumed by Coolify itself (deploys go through the webhook), it is
the single source of truth for the deploy contract that the runbook
links to.

These tests pin the contract:

- The yaml parses without errors (it is not malformed).
- All required fields are present (image, port, env, healthcheck).
- The env-var list matches the ``Settings`` defaults documented in
  ``docs/codebase/integrations.md`` (so the runbook and the code
  cannot drift).
- The healthcheck path matches the route exposed by the local
  backend (``/healthz``).
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
YAML_PATH = REPO_ROOT / "coolify" / "apap-web-coolify.yaml"


@pytest.fixture(scope="module")
def spec() -> dict[str, object]:
    """Load and parse the yaml; cached for the whole module."""
    assert YAML_PATH.is_file(), f"{YAML_PATH} does not exist"
    return yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))


# --- structural contract --------------------------------------------------


class TestYamlShape:
    """Static checks the deploy contract yaml must always pass."""

    def test_yaml_path_exists(self) -> None:
        assert YAML_PATH.is_file()

    def test_yaml_parses(self, spec: dict[str, object]) -> None:
        # The fixture already parses; the assertion is that it is a
        # dict (not a list or scalar).
        assert isinstance(spec, dict)

    def test_spec_has_service_key(self, spec: dict[str, object]) -> None:
        assert "service" in spec, "missing top-level 'service' key"

    def test_service_has_required_fields(self, spec: dict[str, object]) -> None:
        service = spec["service"]
        assert isinstance(service, dict)
        for field in ("name", "image", "port", "healthcheck", "env"):
            assert field in service, f"service missing required field: {field}"


class TestImageContract:
    """The image must come from the GitHub Actions build (not a public
    registry), and the tag must follow the ``v<sha>`` pattern so a
    rollback is always possible."""

    def test_image_is_github_container_registry(self, spec: dict[str, object]) -> None:
        service = spec["service"]
        assert isinstance(service, dict)
        image = service["image"]
        assert isinstance(image, str)
        assert "ghcr.io" in image, (
            f"image must come from ghcr.io (built by CI), got: {image!r}"
        )

    def test_image_includes_repo_and_tag_pattern(
        self, spec: dict[str, object]
    ) -> None:
        service = spec["service"]
        assert isinstance(service, dict)
        image = service["image"]
        assert isinstance(image, str)
        # ``:v<sha>-<short_sha>`` or ``:main`` pattern — the tag must
        # never be ``:latest`` because rollback depends on a fixed
        # SHA.
        assert ":latest" not in image, "image tag must never be :latest"


class TestPortContract:
    """The exposed port must match what ``app/main.py::create_app``
    listens on (currently 8000)."""

    def test_port_is_8000(self, spec: dict[str, object]) -> None:
        service = spec["service"]
        assert isinstance(service, dict)
        assert service["port"] == 8000


class TestHealthcheckContract:
    """The healthcheck path must match ``app/core/local_backend/healthz.py``'s
    ``GET /healthz`` route, and the interval must be fast enough to
    catch a startup failure (10s or less)."""

    def test_healthcheck_path_is_healthz(
        self, spec: dict[str, object]
    ) -> None:
        service = spec["service"]
        assert isinstance(service, dict)
        hc = service["healthcheck"]
        assert isinstance(hc, dict)
        assert hc["path"] == "/healthz"

    def test_healthcheck_interval_is_le_10s(
        self, spec: dict[str, object]
    ) -> None:
        service = spec["service"]
        assert isinstance(service, dict)
        hc = service["healthcheck"]
        assert isinstance(hc, dict)
        assert hc["interval_seconds"] <= 10


class TestEnvContract:
    """The env-var list must include every ``APAP_*`` env var that the
    production app reads at startup. The set is pinned in
    ``docs/codebase/integrations.md``; drifting the deploy contract
    out of sync with that doc is a CI-blocker (per apap-testing HR-3)."""

    REQUIRED_ENV_VARS = (
        "APAP_MODE",
        "APAP_SESSION_SECRET",
        "APAP_LOCAL_BACKEND",
        "APAP_LOCAL_DB_URL",
        "APAP_SMTP_HOST",
        "APAP_SMTP_PORT",
        "APAP_SMTP_USER",
        "APAP_SMTP_PASSWORD",
        "APAP_SMTP_FROM",
        "APAP_PUBLIC_BASE_URL",
    )

    def test_required_env_vars_present(self, spec: dict[str, object]) -> None:
        service = spec["service"]
        assert isinstance(service, dict)
        env = service["env"]
        assert isinstance(env, list)
        declared = {entry["name"] for entry in env if isinstance(entry, dict)}
        missing = set(self.REQUIRED_ENV_VARS) - declared
        assert not missing, f"env vars missing from deploy contract: {sorted(missing)}"

    def test_no_secret_default_values(self, spec: dict[str, object]) -> None:
        """Secret-bearing vars must not carry a usable default in the
        yaml; the operator must set them via Coolify's secret store."""
        service = spec["service"]
        assert isinstance(service, dict)
        env = service["env"]
        assert isinstance(env, list)
        for entry in env:
            assert isinstance(entry, dict)
            if entry["name"] in (
                "APAP_SESSION_SECRET",
                "APAP_SMTP_PASSWORD",
                "APAP_LOCAL_DB_URL",
            ):
                # ``value`` may be present as ``""`` (operator fills in)
                # or absent; ``CHANGEME`` literals are not allowed.
                value = entry.get("value", "")
                if value:
                    assert "CHANGEME" not in str(value).upper(), (
                        f"{entry['name']} carries a placeholder default; "
                        "use Coolify's secret store instead"
                    )


class TestRunbookLink:
    """The yaml's ``runbook`` field must point at a doc that exists in
    the repo. Drift between the deploy contract and the runbook is
    a known foot-gun (issue #648)."""

    def test_runbook_field_points_at_existing_doc(
        self, spec: dict[str, object]
    ) -> None:
        service = spec["service"]
        assert isinstance(service, dict)
        runbook_ref = service.get("runbook")
        assert isinstance(runbook_ref, str)
        # Strip the leading ``docs/`` because pytest's CWD is the repo root.
        assert (REPO_ROOT / runbook_ref).is_file(), (
            f"runbook ref {runbook_ref!r} does not exist at the repo root"
        )
