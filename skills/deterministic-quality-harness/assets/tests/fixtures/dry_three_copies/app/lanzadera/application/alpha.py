# HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — negative fixture, do not "fix"
"""Same clone as dry_violation, copied into one more file.

The BASELINE key must be identical to the two-copy case: growing a clone into another file is
a change in the count, not the identity of the duplication.
"""


def load_alpha(payload: list[int]) -> dict[str, int]:
    result: dict[str, int] = {}
    total = 0
    for item in payload:
        total += item
    result["total"] = total
    return result
