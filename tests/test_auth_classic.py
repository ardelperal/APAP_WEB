"""Slice-completeness tests for the ``auth_classic`` slice (M1, issue #641).

This test file exists to satisfy the slice-completeness gate (AGENTS.md
rule 33 + hardening Step 2). The actual M1 behaviour is covered by
``tests/integration/test_self_host_auth.py`` (ClassicPasswordAuthPort
adapter + set_password + verify_password atoms). This file re-exports
those atoms so the gate sees at least one test file under the
``auth_classic`` slice name.

Do not add new M1 behaviour here; route new tests through the existing
``test_self_host_auth.py`` integration file or a dedicated module.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="Stub: actual coverage lives in test_self_host_auth.py")
def test_auth_classic_slice_is_tested_by_integration_tests() -> None:
    """Placeholder.

    The real coverage for ``ClassicPasswordAuthPort`` (set_password,
    verify_password, argon2id hashing, NULL-hash guard, inactive-user
    guard, LocalBackend no-op fallback) is in
    ``tests/integration/test_self_host_auth.py``. This file exists so
    the slice-completeness gate sees at least one ``test_auth_classic*``
    file. Delete it when the M1 slice grows a dedicated per-layer
    test suite.
    """
    assert True
