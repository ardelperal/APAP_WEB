"""Smoke test for the CI test job.

A single passing assertion so the CI `test` job is never vacuous.
Replaced by real unit and integration tests as application code lands.

The architecture doc (`docs/architecture/architecture-insforge-stack.md § CI/CD Quality Gate`)
promotes DeprecationWarning to error in pytest's `filterwarnings`. This
test intentionally contains no deprecated API calls so the strictness
flag does not fail the smoke check.
"""


def test_smoke_passes() -> None:
    """The test job always has at least one passing test."""
    assert 1 + 1 == 2
