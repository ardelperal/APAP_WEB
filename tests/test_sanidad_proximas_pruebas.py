"""Unit tests for the ``proximas_pruebas`` builder + service.

The builder (``queries.py::build_proximas_pruebas_sql``) is a pure
SQL seam per apap-testing HR-2: it returns ``(sql, params)`` so the
SQL shape is testable without transport. The service
(``service.py::get_proximas_pruebas``) takes the SQL, executes it,
and projects the rows into the ``ProximaPrueba`` dataclass.

These tests do not require Postgres. The integration coverage for
the round-trip lives at ``tests/integration/test_proximas_pruebas.py``
(runs in CI with ``APAP_TEST_POSTGRES_DSN``).

Hard rules (web-tdd-philosophy):

- Rule 1 (fixture gate): each atom builds its own builder input.
- Rule 4 (no humo): assertions on the SQL string + params shape,
  not absence-of-error.
"""
from __future__ import annotations

import re
from datetime import date

from app.modules.sanidad.queries import build_proximas_pruebas_sql

# --- builder --------------------------------------------------------------


class TestBuildProximasPruebasSql:
    """The builder must produce a single SELECT that the executor can
    run in one round-trip. No temp tables, no multi-statement."""

    def test_returns_sql_and_params_tuple(self) -> None:
        result = build_proximas_pruebas_sql(
            fecha_desde=date(2026, 1, 1),
            fecha_hasta=date(2026, 12, 31),
        )
        assert isinstance(result, tuple)
        sql, params = result
        assert isinstance(sql, str)
        # The codebase convention (see ``build_get_animal_nchip`` and
        # ``build_resumen_sanitario``) returns ``list[Any]`` for ``params``
        # — positional binds that line up with ``$N`` placeholders in
        # ``sql``.
        assert isinstance(params, list)

    def test_sql_is_single_select(self) -> None:
        """No ``;`` (the executor runs one statement at a time). The
        statement may start with ``WITH`` (a CTE) or directly with
        ``SELECT`` — both are valid single statements."""
        sql, _ = build_proximas_pruebas_sql(
            fecha_desde=date(2026, 1, 1),
            fecha_hasta=date(2026, 12, 31),
        )
        assert sql.count(";") == 0
        stripped = sql.lstrip().lower()
        assert stripped.startswith("select") or stripped.startswith("with"), (
            f"SQL must start with SELECT or WITH, got: {stripped[:40]!r}"
        )
        # The terminal clause is a ``SELECT`` (the outer query).
        assert "select" in stripped.lower()

    def test_filters_by_fecha_window(self) -> None:
        """The window must be parameter-bounded (``$1``, ``$2``), not
        string-interpolated — sql-injection guard."""
        sql, params = build_proximas_pruebas_sql(
            fecha_desde=date(2026, 1, 1),
            fecha_hasta=date(2026, 12, 31),
        )
        assert "$1" in sql and "$2" in sql, sql
        assert params[0] == "2026-01-01"
        assert params[1] == "2026-12-31"

    def test_excludes_soft_deleted_animals(self) -> None:
        sql, _ = build_proximas_pruebas_sql(
            fecha_desde=date(2026, 1, 1),
            fecha_hasta=date(2026, 12, 31),
        )
        assert "activo" in sql
        # The filter is on the animales table; we use ``activo = true``
        # in the JOIN/WHERE.
        assert re.search(r"activo\s*=\s*true", sql, re.IGNORECASE), sql

    def test_excludes_one_shot_tests(self) -> None:
        """Tests with ``periodicidad_meses IS NULL`` (one-shots like
        Esterilización) have no "next" and must be excluded."""
        sql, _ = build_proximas_pruebas_sql(
            fecha_desde=date(2026, 1, 1),
            fecha_hasta=date(2026, 12, 31),
        )
        # ``periodicidad_meses IS NOT NULL`` is the canonical exclusion.
        assert "periodicidad_meses IS NOT NULL" in sql, sql

    def test_optional_animal_filter(self) -> None:
        """When ``animal_id`` is provided, the query adds a WHERE
        clause; when None, no filter is applied."""
        sql_with, params_with = build_proximas_pruebas_sql(
            fecha_desde=date(2026, 1, 1),
            fecha_hasta=date(2026, 12, 31),
            animal_id="a" * 36,  # looks like a UUID string for testing
        )
        sql_without, params_without = build_proximas_pruebas_sql(
            fecha_desde=date(2026, 1, 1),
            fecha_hasta=date(2026, 12, 31),
            animal_id=None,
        )
        # When animal_id is given, the SQL gains a ``$3`` clause and the
        # params list grows; when None, it does not.
        assert "$3" in sql_with
        assert "a" * 36 in params_with[2]
        assert "$3" not in sql_without
        assert len(params_without) == 2

    def test_optional_tipo_filter(self) -> None:
        sql_with, params_with = build_proximas_pruebas_sql(
            fecha_desde=date(2026, 1, 1),
            fecha_hasta=date(2026, 12, 31),
            tipo_prueba_codigo="Vacuna Polivalente",
        )
        # The codigo must be parameter-bounded (no string interpolation).
        assert "Vacuna Polivalente" not in sql_with
        assert params_with[-1] == "Vacuna Polivalente"

    def test_projects_required_columns(self) -> None:
        """The SELECT must include: chip, nombre_animal, tipo_codigo,
        fecha_ultima, fecha_proxima, periodicidad_meses. The route
        contract depends on these names being stable."""
        sql, _ = build_proximas_pruebas_sql(
            fecha_desde=date(2026, 1, 1),
            fecha_hasta=date(2026, 12, 31),
        )
        for column in (
            "chip",
            "nombre",
            "tipo_codigo",
            "fecha_ultima",
            "fecha_proxima",
            "periodicidad_meses",
        ):
            assert column in sql, f"SELECT missing column: {column}"


# --- estado (the dataclass the service projects) --------------------------


class TestProximaPruebaEstado:
    """The ``estado`` field is derived from the ``fecha_proxima`` vs the
    operator's reference date (``fecha_hasta``). The route serialises
    the string verbatim; the operator UI maps each to a colour.

    Contract:

    - ``vencida``: ``fecha_proxima < fecha_hasta`` (the test was already
      due before the operator's window opened).
    - ``proxima``: ``fecha_hasta <= fecha_proxima <= fecha_hasta + 30d``
      (coming up soon; show on dashboard).
    - ``futura``: ``fecha_proxima > fecha_hasta + 30d`` (further out).
    """

    def test_estado_vencida_when_proxima_before_hasta(self) -> None:
        from app.modules.sanidad.service import _compute_estado

        estado = _compute_estado(
            fecha_proxima=date(2026, 6, 15),
            fecha_hasta=date(2026, 12, 31),
        )
        # 6/15 is well before the window end (12/31) → "vencida".
        assert estado == "vencida"

    def test_estado_proxima_when_proxima_within_30_days_after_hasta(
        self,
    ) -> None:
        from app.modules.sanidad.service import _compute_estado

        estado = _compute_estado(
            fecha_proxima=date(2027, 1, 15),
            fecha_hasta=date(2026, 12, 31),
        )
        # 1/15/2027 is 15 days after 12/31/2026 → within the 30-day
        # "coming up" window → "proxima".
        assert estado == "proxima"

    def test_estado_futura_when_proxima_far_after_hasta(self) -> None:
        from app.modules.sanidad.service import _compute_estado

        estado = _compute_estado(
            fecha_proxima=date(2027, 6, 30),
            fecha_hasta=date(2026, 12, 31),
        )
        # 6/30/2027 is 6 months after 12/31/2026 → outside the 30-day
        # window → "futura".
        assert estado == "futura"
