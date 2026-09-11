"""Hexagonal port surface for the materiales module.

The application layer (and routes) depend on the ``MaterialesPort``
Protocol defined here. The concrete LocalBackend adapter lives
under ``app/modules/materiales/adapters/local_backend/`` (lands in
PR 2 of issue #752). The port carries one method per public use
case from the legacy ``service.py`` and ``estancia_material_service.py``.
"""
