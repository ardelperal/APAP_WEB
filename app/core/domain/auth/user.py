"""Domain entity for a row of ``usuarios_autorizados``.

The dataclass is the canonical shape the application and port layers
exchange; adapters map their transport rows (LocalBackend dict, future
Access DAO Recordset) to this entity via :meth:`from_row`. The class
is immutable (``frozen=True``) per AGENTS.md §1 (no in-place mutation
across the layered boundary).

Why ``added_by`` and ``added_at`` are optional
----------------------------------------------

The legacy SELECT statements in :mod:`app.core.adapters.local_backend.auth_local_backend_queries`
do NOT return ``added_by`` or ``fecha_alta`` for every path:

- ``GET_USER_BY_EMAIL_SQL`` (used by the auth-revalidation cache
  and the duplicate pre-check) selects only ``id, email, rol, activo``
  — a narrower projection so the auth-cache test spy can
  differentiate it from the duplicate-check call (issue #143).
- ``GET_USER_BY_ID_SQL`` and ``DEACTIVATE_USER_SQL`` follow the
  same narrower projection.
- ``LIST_USERS_SQL`` returns ``fecha_alta`` but not ``added_by``
  (it is unused by the admin table view).
- ``ADD_USER_SQL`` returns ``fecha_alta`` plus the column aliased
  as ``anadido_por`` in the INSERT.

The admin tests' SQL pattern matching
(``tests/test_admin.py::_FakeLocalBackend.execute_sql``) keys on the
exact substring ``"SELECT id, email, rol, activo FROM
usuarios_autorizados WHERE id = $1"`` — adding columns to the
projection would break those tests. So the entity exposes
``added_by`` / ``added_at`` as ``Optional`` with ``None`` default;
callers that need them can either extend the SQL (a future slice)
or use the raw dict via the legacy ``app.core.auth`` shim.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.core.domain.auth.rol import Rol


@dataclass(frozen=True, slots=True)
class AuthorizedUser:
    """A row of ``usuarios_autorizados``.

    Attributes:
        id: UUID string minted by the database (``gen_random_uuid()``).
        email: Canonical, normalized email (stripped + lowercased; see
            ``app.core.auth_helpers.normalize_email``).
        rol: One of :class:`Rol`'s values, validated application-side
            (rule 4 — single source of truth per domain concept).
        active: ``True`` when the user is currently authorized. The
            ``deactivate_authorized_user`` use case flips this to
            ``False``; the bootstrap / list views see both states.
        added_by: UUID string of the user that minted this row, or
            ``None`` when the row's source query does not project
            this column (see module docstring for the SQL coverage
            matrix).
        added_at: ``datetime`` at INSERT time, or ``None`` when the
            source query does not project ``fecha_alta``.
    """

    id: str
    email: str
    rol: Rol
    active: bool
    added_by: str | None = None
    added_at: datetime | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> AuthorizedUser:
        """Build an :class:`AuthorizedUser` from a transport-shaped dict.

        The LocalBackend adapter receives rows shaped like
        ``{"id": ..., "email": ..., "rol": ..., "activo": ...}``
        (lowercase Spanish column names, matching the production
        schema in :mod:`app.core.schema_bootstrap`). The ``added_by``
        column is sometimes named ``anadido_por`` (in INSERT
        RETURNING); this constructor accepts either alias.

        Required-by-domain fields default to safe sentinels when
        the source query did not project them — the pre-Phase-1
        ``app.core.auth.list_authorized_users`` returned the raw
        SQL row dict to the template, and Jinja's
        ``{{ user.email }}`` renders an empty string for missing
        keys (rather than raising ``KeyError``). ``from_row`` keeps
        the same contract: an incomplete row becomes a
        shell :class:`AuthorizedUser` whose ``to_dict()`` produces
        the same blank fields the legacy template rendering did.
        The "is the source data actually correct?" check belongs
        in the adapter's domain SQL, not in this entity ctor.
        """
        added_by_raw = row.get("added_by")
        if added_by_raw is None:
            added_by_raw = row.get("anadido_por")
        added_at_raw = row.get("added_at")
        if added_at_raw is None:
            added_at_raw = row.get("fecha_alta")
        if added_at_raw is not None and not isinstance(added_at_raw, datetime):
            # Some drivers hand back a string ISO timestamp; keep it as-is
            # so the shim's to_dict() serialises it the same way the legacy
            # code did. The Optional[datetime] type is best-effort.
            added_at_raw = None
        rol_raw = row.get("rol")
        if rol_raw is not None:
            try:
                rol_value = Rol(str(rol_raw))
            except ValueError:
                # Source SQL returned an unknown role (e.g. a legacy row
                # from before the CHECK constraint was dropped). Default
                # to KEY_USER so the template renders a valid display
                # rather than crashing; the audit gap is logged at the
                # adapter layer, not here.
                rol_value = Rol.KEY_USER
        else:
            rol_value = Rol.KEY_USER
        return cls(
            id=str(row.get("id", "")),
            email=str(row.get("email", "")),
            rol=rol_value,
            active=bool(row.get("activo", True)),
            added_by=str(added_by_raw) if added_by_raw is not None else None,
            added_at=added_at_raw,
        )

    def to_dict(self) -> dict[str, Any]:
        """Project the entity back to the dict shape the legacy callers expect.

        Used by the backward-compat shim at ``app.core.auth`` to keep
        :func:`app.core.auth_dependencies.require_authorized_user` and
        :func:`app.core.auth_flow.callback` working without a signature
        change. New callers should consume the entity directly.

        Only fields that the source query actually populated are
        included: the legacy SQL for ``get_user_by_email`` /
        ``get_user_by_id`` / ``deactivate_authorized_user`` returns
        the narrower 4-column projection
        (``id, email, rol, activo``) and the legacy
        :func:`require_authorized_user` test asserts an exact dict
        match on those four keys — emitting ``"added_by": None``
        for a row whose query never projected the column would
        silently break the test contract.
        """
        result: dict[str, Any] = {
            "id": self.id,
            "email": self.email,
            "rol": self.rol.value,
            "activo": self.active,
        }
        if self.added_by is not None:
            result["added_by"] = self.added_by
        if self.added_at is not None:
            result["added_at"] = self.added_at
        return result
