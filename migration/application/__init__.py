"""Use cases for the migration package.

Each subpackage groups the orchestration functions for one concern.
Use cases depend on the Protocol abstractions in
:mod:`migration.ports`; the concrete adapters are injected by the DI
helpers in :mod:`migration.di`.

The hexagonal split (per AGENTS.md §31) keeps this layer free of
``InsForgeClient`` or DAO imports — every transport-shaped object is
hidden behind a Protocol boundary so use cases are testable with
plain in-memory fakes.
"""

from __future__ import annotations
