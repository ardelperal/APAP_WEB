# HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — positive fixture
"""A domain module that respects every rule: stdlib only, same slice, inward dependencies."""

from dataclasses import dataclass

from app.core.domain.identifiers import UserId  # cross-cutting module, allowed from any slice


@dataclass(frozen=True)
class User:
    identifier: UserId
    email: str

    def is_same_as(self, other: "User") -> bool:
        return self.identifier == other.identifier
