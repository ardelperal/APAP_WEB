"""Local-backend stub adapters — temporary placeholders for the four
InsForge ports retired in issue #666.

Each stub satisfies the corresponding Protocol structurally but raises
:class:`NotImplementedError` on every method, so the runtime fails loud
per route until a real :class:`~app.core.local_backend.db.LocalPostgresExecutor`-backed
adapter lands (tracked as the follow-up to #666).

Import the stubs directly from their modules — the package's ``__init__``
is intentionally empty to avoid the circular-import chain that arises
when :mod:`app.core.domain.auth.__init__` (which itself imports a stub
transitively) ends up loading :mod:`app.core.adapters.stubs.__init__`
while :mod:`app.core.ports.auth_port` is still being initialised.
"""
