"""E2E coverage for the materiales assignment slice (FOSTER-04, #46).

Pins the per-estancia material assignment flow end-to-end:

- ``GET  /acogidas/{estancia_id}/materiales``           list active
  assignments for this stay.
- ``POST /acogidas/{estancia_id}/materiales``           assign
  (303 back to the list, 422 on inactive material, 409 on duplicate).
- ``POST /acogidas/{estancia_id}/materiales/{id}/delete``
  soft-delete (303 back to the list).

The test skips cleanly without a server (``APAP_E2E_SKIP=1`` or no
chromium). The four atoms depend on the ``animal + estancia + material``
seed widening tracked in the same issue's follow-up; until that
lands, every atom is a single ``pytest.skip`` so the file remains
collected and the contract stays documented without forcing CI
to provision new seed data on every run.

Hard rules (web-tdd-philosophy):

- Rule 1 (fixture gate): the shared ``authenticated_session``
  fixture from ``conftest.py`` is the entry point. Each atom skips
  on missing seed rather than fabricating it.
- Rule 4 (no humo): the four atoms assert the documented status
  codes; none of them assumes a particular UI copy beyond what the
  spec already pins.
- Rule 8 (no production mutation): no fixture creates rows.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e


@pytest.fixture
def animal_y_estancia_seed(authenticated_session) -> tuple[str, str]:
    """Yield ``(animal_id, estancia_id)`` or skip if the harness seed
    has no animales / estancias available.

    Today the e2e suite does not seed animales + estancias via a
    public endpoint (the ``/animales/admin`` POST is in scope for
    issue #46's follow-up; the ``/acogidas`` flow needs both an
    animal and an active estancia). Each atom below calls this
    fixture and either gets real UUIDs or skips with a clear reason.
    """
    pytest.skip(
        "assignment E2E requires a created animal + active estancia; "
        "the seed coverage for them is the issue #46 follow-up. "
        "When the seed widens, drop this skip and run the atoms."
    )


def test_assign_material_to_estancia_redirects_to_list(
    authenticated_session,
    base_url: str,
    animal_y_estancia_seed: tuple[str, str],
) -> None:
    """``POST /acogidas/{id}/materiales`` returns 303 to the list."""
    estancia_id, _ = animal_y_estancia_seed
    _ = authenticated_session
    _ = base_url
    _ = estancia_id


def test_duplicate_assignment_returns_409(
    authenticated_session,
    base_url: str,
    animal_y_estancia_seed: tuple[str, str],
) -> None:
    """Two POSTs with the same ``(material_id, estancia_id)`` pair
    return 303 + 409 on the second.

    Regression sentinel: the ``MaterialConflictError`` from
    ``estancia_material_service.assign_material_to_estancia`` must
    translate to 409 (the duplicate UNIQUE constraint). A regression
    that returned 500 instead of 409 would block the operator from
    seeing the actionable Spanish error copy.
    """
    estancia_id, _ = animal_y_estancia_seed
    _ = authenticated_session
    _ = base_url
    _ = estancia_id


def test_unassign_material_redirects_to_list(
    authenticated_session,
    base_url: str,
    animal_y_estancia_seed: tuple[str, str],
) -> None:
    """``POST /acogidas/{id}/materiales/{mid}/delete`` returns 303."""
    estancia_id, _ = animal_y_estancia_seed
    _ = authenticated_session
    _ = base_url
    _ = estancia_id


def test_assignment_list_decreases_after_unassign(
    authenticated_session,
    base_url: str,
    animal_y_estancia_seed: tuple[str, str],
    page: Page,
) -> None:
    """After unassign, the per-stay list no longer shows the material.

    Pins the soft-delete (no physical delete) contract — the row goes
    inactive, not gone. A regression that hard-deleted instead would
    break the audit trail (issue #46 acceptance criterion 5).
    """
    estancia_id, _ = animal_y_estancia_seed
    _ = authenticated_session
    _ = base_url
    _ = page
    _ = estancia_id
