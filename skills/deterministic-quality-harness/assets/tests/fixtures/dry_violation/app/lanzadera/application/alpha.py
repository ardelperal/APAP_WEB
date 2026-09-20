# HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — negative fixture, do not "fix"
"""First half of a copy-paste pair. See beta.py — same shape, every name changed."""


def load_alpha(payload: list[int]) -> dict[str, int]:
    result: dict[str, int] = {}
    total = 0
    for item in payload:
        total += item
    result["total"] = total
    return result
