# HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — positive fixture
"""Every function here sits well under the ceiling."""


def classify(value: int) -> str:
    if value < 0:
        return "negative"
    if value == 0:
        return "zero"
    return "positive"


def summarise(values: list[int]) -> dict[str, int]:
    counts = {"negative": 0, "zero": 0, "positive": 0}
    for value in values:
        counts[classify(value)] += 1
    return counts
