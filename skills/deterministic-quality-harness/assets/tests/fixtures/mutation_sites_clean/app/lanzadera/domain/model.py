# HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — positive fixture
"""A small module with a small mutation surface."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Expediente:
    identifier: int
    estado: str

    def is_open(self) -> bool:
        return self.estado == "abierto"
