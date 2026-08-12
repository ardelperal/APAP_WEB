"""Composition root subpackage for the lifecycle slice (LIFECYCLE-03 PR-B).

The DI factory is exported from :mod:`app.modules.lifecycle.di.lifecycle_di`
and re-exported here as the package surface so cross-module consumers
follow AGENTS.md §27 (import from the package, never the submodule).
"""
from app.modules.lifecycle.di.lifecycle_di import build_lifecycle_port

__all__ = ["build_lifecycle_port"]
