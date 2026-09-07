"""Adapters layer — Cesiones slice.

The LocalBackend adapter implementation was deleted in issue #668; until a
real ``LocalPostgresExecutor``-backed adapter lands (tracked as the
follow-up), the slice's DI provider yields a :class:`StubCesionesPort`
placeholder that raises :class:`NotImplementedError` on every method
call (see ``app.modules.cesiones.adapters.stubs.cesiones_stub``).
"""
