"""Public API for the lifecycle slice (LIFECYCLE-03, PR-A)."""

from app.modules.lifecycle.domain.animal_state import (
    DerivationKind,
    DerivationResult,
    calculate_state,
)

__all__ = ["DerivationKind", "DerivationResult", "calculate_state"]
