"""Hexagonal ports for the migration package.

Each submodule declares one :class:`~typing.Protocol` per adapter-side
concern. Adapters live under :mod:`migration.adapters`; use cases
under :mod:`migration.application`. This package is the abstract
surface use cases depend on — nothing in here imports an LocalBackend or
DAO client directly.
"""

from __future__ import annotations
