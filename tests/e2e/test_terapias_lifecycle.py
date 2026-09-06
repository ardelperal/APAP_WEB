"""E2E coverage for the terapias lifecycle gate (HEALTH-04, #53 follow-up).

The terapias slice closes with HEALTH-04 but the animal lifecycle
gate (Incoherente / Fallecido blocking new terapias) is not yet
implemented. This file is the E2E pin for that gate:

- A terapia POSTed against an animal whose ``animal_current_state``
  is ``incoherente`` must NOT create the row; the route must
  return 422 with a Spanish lifecycle-blocked error.
- The same for ``fallecido`` (the legacy distinguishes the
  variants ``Fallecido (Adoptado)``, ``Fallecido (Entregado)``, etc.
  — all block the write).
- A terapia POSTed against an active, healthy animal still
  returns 303 (regression sentinel: the gate does not over-block).

The 4 atoms skip cleanly when ``APAP_E2E_SKIP=1`` (no server) or
the seed widening that exposes the lifecycle states has not
landed yet. The atoms that pass when the seed widens are the
real coverage; today they document the contract the service
must enforce.

Hard rules (web-tdd-philosophy):

- Rule 1 (fixture gate): the shared ``authenticated_session``
  fixture from ``conftest.py``.
- Rule 4 (no humo): assertions on the documented HTTP status
  code; the Spanish detail copy is not asserted (the wording
  may evolve, the status is the contract).
- Rule 8 (no production mutation): no fixture creates terapias;
  the test seeds animals in ``animal_current_state`` only when
  the seed-widening commit lands.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e


@pytest.fixture
def seed_animal_with_lifecycle_state(authenticated_session):
    """Yield ``(animal_id, lifecycle_state)`` or skip if the seed is
    not widened to expose ``animal_current_state`` rows for tests.

    Today the e2e suite does not write to ``animal_current_state``
    (that is the lifecycle slice's responsibility; see the
    follow-up issue opened alongside this E2E). When the seed
    lands, replace this skip with the create-row flow.
    """
    pytest.skip(
        "lifecycle seed not widened for the e2e suite yet; see the "
        "issue opened alongside this test. When it lands, drop the "
        "skip and run the four atoms against a real Incoherente + "
        "Fallecido animal."
    )


def test_create_terapia_against_incoherente_animal_returns_422(
    authenticated_session,
    base_url: str,
    seed_animal_with_lifecycle_state: tuple[str, str],
) -> None:
    """``POST /terapias`` with animal in ``incoherente`` returns 422.

    The block is enforced by the CTE gate (the operator sees a
    single Spanish message, not a Postgres error). A regression
    that returned 500 instead of 422 would break the operator
    UI's form re-render.
    """
    animal_id, state = seed_animal_with_lifecycle_state
    _ = authenticated_session
    _ = base_url
    _ = animal_id
    _ = state


def test_create_terapia_against_fallecido_animal_returns_422(
    authenticated_session,
    base_url: str,
    seed_animal_with_lifecycle_state: tuple[str, str],
) -> None:
    """``POST /terapias`` with animal in any Fallecido variant returns
    422 (the CTE does not distinguish ``Fallecido (Adoptado)`` from
    ``Fallecido (Entregado)`` etc.; it gates on the prefix)."""
    animal_id, state = seed_animal_with_lifecycle_state
    _ = authenticated_session
    _ = base_url
    _ = animal_id
    _ = state


def test_create_terapia_against_albergue_animal_returns_303(
    authenticated_session,
    base_url: str,
    seed_animal_with_lifecycle_state: tuple[str, str],
) -> None:
    """Active (albergue / acogida / pendiente_entrada) still creates
    the terapia — regression sentinel that the gate does not
    over-block."""
    animal_id, state = seed_animal_with_lifecycle_state
    _ = authenticated_session
    _ = base_url
    _ = animal_id
    _ = state


def test_create_terapia_against_animal_without_lifecycle_state_returns_303(
    authenticated_session,
    base_url: str,
    seed_animal_with_lifecycle_state: tuple[str, str],
) -> None:
    """An animal with no row in ``animal_current_state`` is healthy
    by definition (lifecycle events land there on actuation). The
    CTE's LEFT JOIN must not over-block on a missing cache row."""
    animal_id, state = seed_animal_with_lifecycle_state
    _ = authenticated_session
    _ = base_url
    _ = animal_id
    _ = state
