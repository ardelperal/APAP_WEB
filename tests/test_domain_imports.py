"""Guard against circular imports when domain.py is split into sub-modules.

The split places SQL constants and Pydantic models into 9 cohesive
``app.core.domain_*`` modules.  Python's import system can silently
introduce import cycles when sub-modules cross-reference each other.
This test randomises the import order (10 seeds) and verifies that
``import app.core.domain`` succeeds without ``ImportError`` in every case.

The test is intentionally a *regression guard*: the current monolithic
``app/core/domain.py`` has no internal cycles, so the test passes today.
After the split, if a future change accidentally introduces a cycle,
one or more seeds will fail.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

# The 9 domain sub-modules produced by the split.
DOMAIN_MODULES = [
    "app.core.domain_animales",
    "app.core.domain_voluntarios",
    "app.core.domain_entradas",
    "app.core.domain_foster",
    "app.core.domain_adopciones",
    "app.core.domain_lifecycle",
    "app.core.domain_cesiones",
    "app.core.domain_contracts",
    "app.core.domain_salud",
    "app.core.domain_materiales",
]


@pytest.mark.parametrize("seed", range(10))
def test_domain_no_circular_imports(seed: int) -> None:
    """Import app.core.domain in a fresh interpreter after random module loads.

    Uses ``subprocess`` to spawn an isolated Python interpreter so module
    state from the test runner does not mask a cycle in the application
    code itself.
    """
    # Shuffle the import order based on the seed to catch order-dependent cycles.
    # Deterministic per seed so failures are reproducible.
    import random

    random.seed(seed)
    ordered = DOMAIN_MODULES.copy()
    random.shuffle(ordered)

    # Force Python to preload each sub-module in the randomised order before
    # importing the monolithic shim.  The script exits 0 only if every import
    # succeeds without raising ImportError.
    code_lines = [
        "import sys",
        "sys.path.insert(0, '.')",
        *[f"import {mod}" for mod in ordered],
        # The shim re-exports everything; this is the canonical entry point.
        "import app.core.domain",
        "print('OK')",
    ]
    code = "\n".join(code_lines)

    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd="issue-289-split-services" if __spec__ is None else None,
    )
    # Provide concrete evidence in the assertion message.
    assert result.returncode == 0, (
        f"Seed {seed}: import failed with returncode {result.returncode}.\n"
        f"stdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )
    assert "OK" in result.stdout, (
        f"Seed {seed}: interpreter exited 0 but did not print OK.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
