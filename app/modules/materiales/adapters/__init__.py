"""Adapters for the materiales bounded context.

The concrete ``LocalBackend`` adapter lives in
``adapters/local_backend/materiales_local_backend_adapter.py`` (PR 2
of issue #752). This directory hosts transport-bound implementations
of the ``MaterialesPort`` Protocol — domain and ports stay
transport-free (PR 1 pins that invariant in
``tests/test_slice_materiales_architecture.py``).
"""
