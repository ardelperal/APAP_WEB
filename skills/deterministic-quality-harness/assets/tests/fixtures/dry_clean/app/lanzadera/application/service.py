# HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — positive fixture
"""Two functions that share a domain but not a shape."""


def total(values: list[int]) -> int:
    return sum(values)


def label(value: int) -> str:
    if value > 0:
        return "positive"
    return "non-positive"
