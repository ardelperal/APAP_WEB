"""Use cases for the authenticated-user management slice.

Each module in this package is a single use case: a thin function that
takes a :class:`~app.core.ports.auth_port.AuthUsersPort` plus the
parameters it needs, applies domain validation, and returns the
result. There is no SQL, no transport envelope, and no logger import
inside these modules — the hexagonal split means the application layer
is the place where the domain rules live, not where the database
talks.

The legacy ``app.core.auth`` module re-exports these functions with
the pre-Phase-1 signatures so the existing callers
(``auth_dependencies``, ``auth_flow``, ``admin_handlers``, ...) keep
working without a signature change.
"""
