# HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — positive companion
"""A perfectly classifiable file, so the gate's failure can only come from its neighbour."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Expediente:
    identifier: int
