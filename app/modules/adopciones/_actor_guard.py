"""Actor guard for the ``update_adopcion`` return transition (issue #945, A-13).

``app/modules/adopciones/service.py`` is a mutation-site ratchet baseline
(``scripts/check_mutation_sites.py``) with no headroom, and
``update_adopcion`` is a CRAP-score ratchet baseline
(``scripts/check_crap.py``) with no headroom either. Adding the "does
this update need an acting user?" branch directly inside
``update_adopcion`` would grow both. Keeping the branch here instead lets
``update_adopcion`` call this helper unconditionally — one call, no new
branch of its own, so its CRAP grade is unchanged.
"""

from __future__ import annotations

from typing import Any, Protocol

from app.core.forms import optional_text
from app.modules.animals import require_actor


class _HasFechaDevolucion(Protocol):
    """The only field of ``Adopcion`` this guard reads.

    A structural type instead of importing ``Adopcion`` keeps this module
    out of the ``adopciones`` package import cycle (``check_import_cycles``).
    """

    @property
    def fecha_devolucion(self) -> str | None: ...


def require_actor_for_return(
    previous: _HasFechaDevolucion | None,
    params: dict[str, Any],
    actor_user_id: str | None,
) -> None:
    """Raise unless a return transition has a valid acting user.

    A return transition is ``previous`` having no ``fecha_devolucion``
    yet and ``params`` setting one (the same test ``update_adopcion``
    uses afterwards to decide whether to emit ``ADOPTION_RETURNED``).
    That event needs ``created_by`` as a UUID (maintainer decision,
    option a for issue #945): reject before the ``UPDATE`` runs when
    there is no actor. A non-return update never raises here.
    """
    if (
        previous is not None
        and previous.fecha_devolucion is None
        and optional_text(params, "fecha_devolucion")
    ):
        require_actor(actor_user_id)


__all__ = ["require_actor_for_return"]
