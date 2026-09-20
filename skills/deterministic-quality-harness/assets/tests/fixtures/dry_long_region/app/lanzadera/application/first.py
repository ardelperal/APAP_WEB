# HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — negative fixture, do not "fix"
"""A long duplicated region, to pin that it is reported ONCE and not once per window offset."""


def build_first(rows: list[int]) -> dict[str, int]:
    result: dict[str, int] = {}
    total = 0
    count = 0
    for item in rows:
        total += item
    result["total"] = total
    return result
