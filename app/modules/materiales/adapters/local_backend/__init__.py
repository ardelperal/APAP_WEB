"""LocalBackend adapter for the materiales slice.

Hosts :class:`LocalBackendMaterialesAdapter` (PR 2 of issue #752) —
the only layer in the slice allowed to import ``SqlExecutor`` /
``app.core.local_backend``. Domain, ports, and (forthcoming) the
application layer depend on the ``MaterialesPort`` Protocol only.
"""
