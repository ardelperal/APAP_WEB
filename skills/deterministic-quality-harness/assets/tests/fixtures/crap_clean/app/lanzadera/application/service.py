# HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — positive fixture
"""Small and fully covered: CRAP collapses to the complexity, which is well under the ceiling."""


def safe(value: int) -> str:
    if value < 0:
        return "negative"
    return "non-negative"
