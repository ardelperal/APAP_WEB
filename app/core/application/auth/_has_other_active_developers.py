"""Use case: check whether at least one other active developer exists.

Used by the ``app.core.auth`` backward-compat shim to preserve the
pre-Phase-1 ``_has_other_active_developers(client, exclude_user_id)``
contract that the admin tests mock. The shim wraps this use case
because the SQL is adapter-bound (the legacy helper ran ``SELECT
EXISTS(...)`` directly against the transport) and the helper is NOT
on :class:`~app.core.ports.auth_port.AuthUsersPort` — exposing it on
the port would invite use-case callers to bypass the last-developer
guard by reading the helper directly instead of letting
``port.deactivate_authorized_user`` handle the disambiguation
internally.

The use case dispatches to ``port._has_other_active_developers`` —
a private method the adapter implements. The Protocol does not
declare it; ``getattr`` is the only sanctioned call site so a future
adapter that drops the helper is caught at first invocation
(``NotImplementedError``), not at first deactivation.
"""
from __future__ import annotations

from app.core.ports.auth_port import AuthUsersPort


def has_other_active_developers(
    port: AuthUsersPort,
    exclude_user_id: str,
) -> bool:
    """Return True if at least one other active developer exists.

    Internal helper for the last-developer guard. The shim's
    ``app.core.auth._has_other_active_developers(client, ...)`` is
    the only sanctioned external caller; new use cases should let
    :func:`deactivate_authorized_user` handle the guard internally
    rather than calling this directly.
    """
    impl = getattr(port, "_has_other_active_developers", None)
    if impl is None:
        # Fail loudly: a future adapter port that drops the helper
        # is caught at first call, not at first deactivation.
        raise NotImplementedError(
            "AuthUsersPort adapter must implement _has_other_active_developers; "
            "this use case is an internal seam for the last-developer guard."
        )
    return impl(exclude_user_id)
