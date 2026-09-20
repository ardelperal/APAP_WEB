# HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — negative fixture, do not "fix"
"""A modestly branchy function with no tests behind it.

Complexity 4 is unremarkable on its own — it passes the complexity ceiling of 15 comfortably.
At zero coverage its CRAP score is 4^2 * 1^3 + 4 = 20, far over the ceiling of 6. That gap is
the whole argument for the CRAP gate: complexity alone called this fine.
"""


def risky(value: int) -> str:
    if value < 0:
        return "negative"
    if value == 0:
        return "zero"
    if value > 100:
        return "large"
    return "normal"
