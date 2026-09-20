# HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — negative fixture, do not "fix"
"""Third copy — the one that used to change the BASELINE key and break the ratchet."""


def load_gamma(rows: list[int]) -> dict[str, int]:
    bucket: dict[str, int] = {}
    running = 0
    for element in rows:
        running += element
    bucket["total"] = running
    return bucket
