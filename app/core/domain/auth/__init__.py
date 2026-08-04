"""Domain entities for authenticated user management (Phase 1 hexagonal slice).

The :class:`AuthorizedUser` dataclass and the :class:`Rol` enum are the
domain shape for the ``usuarios_autorizados`` table. They live here so
that the application (use-case) layer never imports from the transport
adapter, and so that future adapters (e.g. a legacy Access adapter in
Phase 3) can populate the same entities from a different transport.
"""
