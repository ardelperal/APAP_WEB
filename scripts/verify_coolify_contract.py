"""Isolated verifier for the Coolify deploy config contract.

Mirrors gentle-ai's ``internal/releasepolicy/policy.go`` pattern: the
canonical expected config is embedded as a ``_CANONICAL_YAML`` literal
inside this module so the verifier cannot depend on the tree it
validates. The contract under test is at
``coolify/apap-web-coolify.yaml`` (relative to the repo root).

This is part of the APAP_WEB release-side CI/CD reform (Gap 3 of the
prior analysis). See
``docs/codebase/orchestrator-discipline.md`` §17 for the delegation
rules that bound the slice that introduced this verifier; the
verifier itself is a deploy-time contract gate, not an
application-code gate.

Run it directly::

    python scripts/verify_coolify_contract.py coolify/apap-web-coolify.yaml

Exit codes:

* ``0`` — the actual config matches the canonical exactly.
* ``1`` — the actual config drifted (structural or value mismatch).
* ``2`` — the config file is missing or unreadable.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

# --- Canonical contract ----------------------------------------------------

# Embedded as a YAML literal so the verifier imports cleanly and the
# canonical travels with the module — no on-disk dependency on the
# tree it validates. To change the contract, edit BOTH this literal
# AND ``coolify/apap-web-coolify.yaml`` in the same PR.
_CANONICAL_YAML: str = """\
service:
  name: apap-web
  description: |
    APAP_WEB FastAPI application + the local_backend API in the same
    process. The container replaces LocalBackend in production via the
    APAP_LOCAL_BACKEND=true switch (issue #641 / M0-M3.4).
  image: ghcr.io/ardelperal/apap-web:v{short_sha}
  port: 8000
  healthcheck:
    path: /healthz
    interval_seconds: 10
    timeout_seconds: 3
    start_period_seconds: 30
    failure_threshold: 3
  env:
    - name: APAP_MODE
      value: web
    - name: APAP_SESSION_SECRET
      value: ""
    - name: APAP_LOCAL_BACKEND
      value: "true"
    - name: APAP_LOCAL_DB_URL
      value: ""
    - name: APAP_SMTP_HOST
      value: ""
    - name: APAP_SMTP_PORT
      value: "587"
    - name: APAP_SMTP_USER
      value: ""
    - name: APAP_SMTP_PASSWORD
      value: ""
    - name: APAP_SMTP_FROM
      value: onboarding@resend.dev
    - name: APAP_PUBLIC_BASE_URL
      value: https://apap.romancaba.com
  runbook: docs/runbooks/operator-deploy-2026.md
"""

CANONICAL_CONFIG: dict[str, Any] = yaml.safe_load(_CANONICAL_YAML)


# --- Diff machinery --------------------------------------------------------


def _diff(actual: Any, expected: Any, path: str) -> list[str]:
    """Return a flat list of human-readable diffs under ``path``.

    A diff string names one discrepancy between ``actual`` and
    ``expected`` at the given JSON-pointer-style path. Empty list
    means structurally equal.
    """
    diffs: list[str] = []
    if type(actual) is not type(expected):
        diffs.append(
            f"{path}: type mismatch (actual={type(actual).__name__}, "
            f"expected={type(expected).__name__})"
        )
        return diffs
    if isinstance(expected, dict):
        for key in expected:
            if key not in actual:
                diffs.append(f"{path}.{key}: missing (expected value)")
                continue
            diffs.extend(_diff(actual[key], expected[key], f"{path}.{key}"))
        for key in actual:
            if key not in expected:
                diffs.append(f"{path}.{key}: unexpected (not in canonical)")
        return diffs
    if isinstance(expected, list):
        if len(actual) != len(expected):
            diffs.append(
                f"{path}: list length mismatch (actual={len(actual)}, "
                f"expected={len(expected)})"
            )
        for index, item in enumerate(expected):
            if index >= len(actual):
                diffs.append(f"{path}[{index}]: missing")
                continue
            diffs.extend(_diff(actual[index], item, f"{path}[{index}]"))
        return diffs
    if actual != expected:
        diffs.append(
            f"{path}: value mismatch (actual={actual!r}, expected={expected!r})"
        )
    return diffs


# --- Public API ------------------------------------------------------------


def verify(config_path: str) -> None:
    """Compare ``config_path`` against ``CANONICAL_CONFIG`` and exit on drift.

    Raises ``SystemExit(1)`` on any structural or value drift with a
    list of specific diffs annotated for the GitHub Actions runner
    (``::error::`` prefix on each line). Raises ``SystemExit(2)`` if
    the file is missing or unreadable.

    The diffs are emitted on stderr because GitHub Actions only
    annotates ``::error::`` markers in stderr, not stdout.
    """
    path = Path(config_path)
    if not path.is_file():
        sys.stderr.write(
            f"::error::coolify contract verifier: config not found at {config_path}\n"
        )
        sys.exit(2)

    try:
        actual = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        sys.stderr.write(
            f"::error::coolify contract verifier: failed to parse "
            f"{config_path}: {exc}\n"
        )
        sys.exit(2)

    if not isinstance(actual, dict):
        sys.stderr.write(
            "::error::coolify contract verifier: top-level must be a mapping, "
            f"got {type(actual).__name__}\n"
        )
        sys.exit(1)

    diffs = _diff(actual, CANONICAL_CONFIG, "$")
    if diffs:
        sys.stderr.write(
            "::error::coolify contract drift detected — verifier expects the "
            "exact canonical config; update the canonical in scripts/"
            "verify_coolify_contract.py alongside any intended change.\n"
        )
        for diff in diffs:
            sys.stderr.write(f"::error::coolify contract: {diff}\n")
        sys.exit(1)


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "coolify/apap-web-coolify.yaml"
    verify(target)
