"""Hexagonal port surface for the materiales module.

The application layer (and routes) depend on the ``MaterialesPort``
Protocol defined in :mod:`app.modules.materiales.ports.materiales_port`.
The concrete LocalBackend adapter lives under
``app/modules/materiales/adapters/local_backend/``. The port carries
one method per public use case from the application layer.
"""
