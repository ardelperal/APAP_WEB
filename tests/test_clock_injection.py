"""Clock-injection pins for the date-deciding code (issue #1097).

The 2026-07-05 UTC CI break: a test pinned ``fecha: '2026-07-04'`` and,
past midnight, it stopped matching ``date.today()``. The date-deciding
production code now accepts an injectable reference date, so these tests
pin behaviour against a FIXED date far from the wall clock — if any of
them regressed to reading ``date.today()``, the assertions would flip
depending on when CI runs.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.core.tasks.rules import rule_vacuna_vencimiento
from app.modules.sanidad.periodicity import _priority_from_date
from app.modules.sanidad.service import _validate_fecha_d24

#: A reference date nowhere near the wall clock: every assertion below is
#: a pure function of this value.
FIXED_TODAY = date(2026, 1, 15)


def test_vacuna_rule_drafts_from_the_injected_clock() -> None:
    """The 7-day vaccine threshold is measured from ``ctx['today']``.

    A vaccine expiring 2026-01-20 is 5 days from the injected today and
    MUST draft; one expiring 2026-06-01 is far away and MUST NOT — this
    only holds deterministically when the rule reads the injected clock.
    """
    ctx: dict[str, object] = {
        "today": FIXED_TODAY,
        "vacunas": [
            {"animal_id": "a-1", "vacuna_tipo": "rabia", "fecha_vencimiento": "2026-01-20"},
            {"animal_id": "a-2", "vacuna_tipo": "rabia", "fecha_vencimiento": "2026-06-01"},
        ],
    }

    drafts = rule_vacuna_vencimiento(ctx)

    assert [d.vinculo_id for d in drafts] == ["a-1"], (
        "the rule must measure urgency from the injected today (issue #1097)"
    )
    assert drafts[0].metadata["dias_hasta_vencimiento"] == 5


def test_priority_from_date_with_the_injected_clock() -> None:
    """Priority is a pure function of (due_date, today)."""
    # 26 days overdue from the injected today -> alta (would be 'baja'
    # against the real 2026 clock).
    assert _priority_from_date(date(2025, 12, 20), today=FIXED_TODAY) == "alta"
    # 40 days overdue -> urgente.
    assert _priority_from_date(date(2025, 12, 6), today=FIXED_TODAY) == "urgente"
    # Not yet due -> baja.
    assert _priority_from_date(date(2026, 3, 1), today=FIXED_TODAY) == "baja"


def test_sanidad_future_date_validation_with_the_injected_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The D-24 future-date rule measures 'future' from the injected today."""
    import app.modules.sanidad.service as sanidad_service

    monkeypatch.setattr(sanidad_service, "_today", lambda: FIXED_TODAY)
    # 2099-01-01 is future relative to the injected today...
    error = _validate_fecha_d24("2099-01-01")
    assert error == "fecha no puede ser futura (hoy es 2026-01-15)", (
        "the future-date rule must measure from the injected today (issue #1097)"
    )
    # ...and it is the injected date that surfaces in the message.
    assert _validate_fecha_d24("2026-01-14") is None
