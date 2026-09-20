# HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — negative fixture, do not "fix"
"""Second copy."""


def load_beta(records: list[int]) -> dict[str, int]:
    output: dict[str, int] = {}
    accumulator = 0
    for entry in records:
        accumulator += entry
    output["total"] = accumulator
    return output
