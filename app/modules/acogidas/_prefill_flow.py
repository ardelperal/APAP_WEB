"""Query-param prefill flow for ``GET /acogidas/new`` (issue #1008).

``app/modules/acogidas/routes.py`` is a mutation-site ratchet baseline
(``scripts/check_mutation_sites.py``) with no headroom, so the
``/asignar`` redirect-query validation lives here instead of growing the
route body — same extraction pattern as ``_actor_flow.py`` (issue #945,
A-13).

Contract consumed (produced by ``POST /casas-acogida/{id}/asignar``,
issues #142 + #919):

- ``animal_id``: MUST be a well-formed UUID referencing an existing
  animal, otherwise the request 404s — consistent with how
  ``GET /acogidas/{id}`` treats unknown ids. The check goes through the
  slice's injected ``AnimalsPort`` (same dependency the create/update
  routes already carry). The canonical UUID string form is what gets
  echoed into the form, never the raw query value.
- ``casa_acogida_id``: MUST be a well-formed UUID (malformed → 404,
  fail-closed: a non-UUID can never reference a row, mirroring the
  detail routes' not-found outcome). A well-formed but nonexistent casa
  is prefilled and rejected at submit time instead: the foster slice
  does not expose its casa lookup through its public package root
  (``check_layers`` slice-internals rule), and this lane does not own
  ``app/modules/foster/**``, so the existence check cannot be imported
  here without expanding another slice's API. ``create_acogida``'s
  reference validation already fails closed on an unknown casa with a
  422 and an actionable message. The producer only ever redirects with
  a casa it just evaluated, so this branch only fires on hand-crafted
  URLs.
- ``override_id``: rendered into the hidden form field ONLY when it is
  a well-formed UUID (canonical form). A malformed value is silently
  dropped — it must never be reflected into the HTML unvalidated
  (reflected-garbage guard). There is deliberately no DB existence
  check: a stale-but-well-formed id no-ops at create time (the
  ``foster_capacity_overrides`` UPDATE matches 0 rows), so a stale link
  must not block the operator's create flow with a 404.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, Request, status

from app.modules.animals import AnimalsPort, get_animal_by_id


def _canonical_uuid_or_none(value: str) -> str | None:
    """Return ``value`` in canonical UUID form, or ``None`` if malformed."""
    try:
        return str(uuid.UUID(value))
    except (TypeError, ValueError):
        return None


def _resolve_animal_prefill(port: AnimalsPort, raw: str | None) -> str | None:
    """Validate + canonicalize ``animal_id``, or 404 (module docstring)."""
    if not raw:
        return None
    canonical = _canonical_uuid_or_none(raw)
    if canonical is None or get_animal_by_id(port, canonical) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return canonical


def _resolve_casa_prefill(raw: str | None) -> str | None:
    """Validate + canonicalize ``casa_acogida_id``, or 404 when malformed."""
    if not raw:
        return None
    canonical = _canonical_uuid_or_none(raw)
    if canonical is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return canonical


def _resolve_override_prefill(raw: str | None) -> str | None:
    """Canonicalize ``override_id``; malformed values are dropped, never echoed."""
    if not raw:
        return None
    return _canonical_uuid_or_none(raw)


def prefill_form_data_from_query(
    port: AnimalsPort,
    request: Request,
) -> dict[str, Any]:
    """Resolve the ``/asignar`` redirect query into create-form prefill.

    Reads ``animal_id`` / ``casa_acogida_id`` / ``override_id`` from
    ``request.query_params`` and returns the ``form_data`` dict for
    ``_render_form``: only the keys actually carried by the query are
    set, so every other field stays empty. Prefill never overrides
    explicit form values by construction: ``GET /new`` has no other
    ``form_data`` source, and the POST resubmit path (the 422 re-render
    after a failed create) does not read query params, so
    operator-entered values always win.

    Raises:
        HTTPException: 404 when ``animal_id`` is malformed or references
            a nonexistent animal, or when ``casa_acogida_id`` is
            malformed (see module docstring).
    """
    query = request.query_params
    form_data: dict[str, Any] = {}
    animal = _resolve_animal_prefill(port, query.get("animal_id"))
    if animal:
        form_data["animal_id"] = animal
    casa = _resolve_casa_prefill(query.get("casa_acogida_id"))
    if casa:
        form_data["casa_acogida_id"] = casa
    # Issue #1008 (extends #142): the hidden field is the only surface
    # an override_id may reach the create POST through, and only in
    # validated canonical form.
    override = _resolve_override_prefill(query.get("override_id"))
    if override:
        form_data["override_id"] = override
    return form_data
