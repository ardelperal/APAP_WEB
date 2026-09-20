# HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — negative fixture, do not "fix"
"""Second half of the copy-paste pair.

Every identifier differs from alpha.py, so a text-based clone detector finds nothing here. The
normalised AST is identical, which is the point of type-2 detection.
"""


def load_beta(records: list[int]) -> dict[str, int]:
    output: dict[str, int] = {}
    accumulator = 0
    for entry in records:
        accumulator += entry
    output["total"] = accumulator
    return output
