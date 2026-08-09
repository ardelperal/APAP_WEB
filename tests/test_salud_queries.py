"""Query-layer tests for HEALTH-04 salud (queries.py).

Asserts SQL shape and parameter ordering per AGENTS.md §22.
Mirrors ``tests/test_sanidad_queries.py``.
"""

from __future__ import annotations

import re

from app.modules.salud import queries as salud_queries


def _assert_params_count(sql: str, expected: int) -> None:
    params = re.findall(r"\$[0-9]+", sql)
    actual_max = max((int(p[1:]) for p in params), default=0)
    assert actual_max == expected, (
        f"expected {expected} params but found params up to ${actual_max}"
    )


class TestBuildCreateTerapia:
    def test_sql_is_cte_with_fk_checks(self) -> None:
        sql, _ = salud_queries.build_create_terapia({
            "animal_id": "a",
            "voluntario_id": "b",
            "fecha": "2026-07-04",
            "descripcion": "desc",
        })
        assert "checked_animal AS" in sql
        assert "checked_voluntario AS" in sql
        assert "INSERT INTO terapias" in sql
        assert "RETURNING" in sql

    def test_params_order(self) -> None:
        _, params = salud_queries.build_create_terapia({
            "animal_id": "a-id",
            "voluntario_id": "b-id",
            "fecha": "2026-07-04",
            "descripcion": "desc text",
        })
        assert params == ["a-id", "b-id", "2026-07-04", "desc text"]

    def test_params_count(self) -> None:
        sql, params = salud_queries.build_create_terapia({
            "animal_id": "a",
            "voluntario_id": "b",
            "fecha": "2026-07-04",
            "descripcion": None,
        })
        assert len(params) == 4
        _assert_params_count(sql, 4)


class TestBuildListTerapias:
    def test_global_list_sql(self) -> None:
        sql, params = salud_queries.build_list_terapias()
        assert "terapias" in sql
        assert "activo = true" in sql
        assert "ORDER BY fecha DESC" in sql
        assert "LIMIT 100" in sql
        assert params == []

    def test_filtered_by_animal_sql(self) -> None:
        sql, params = salud_queries.build_list_terapias(
            animal_id="ccccccccc-cccc-cccc-cccc-cccccccccc"
        )
        assert "animal_id = $1" in sql
        assert params == ["ccccccccc-cccc-cccc-cccc-cccccccccc"]
        _assert_params_count(sql, 1)


class TestBuildGetTerapia:
    def test_sql_selects_by_id(self) -> None:
        sql, params = salud_queries.build_get_terapia("t-id")
        assert "FROM terapias WHERE id = $1" in sql
        assert params == ["t-id"]
        _assert_params_count(sql, 1)


class TestBuildUpdateTerapia:
    def test_sql_is_cte_with_fk_checks(self) -> None:
        sql, _ = salud_queries.build_update_terapia("t-id", {
            "animal_id": "a",
            "voluntario_id": "b",
            "fecha": "2026-07-04",
            "descripcion": "d",
        })
        assert "checked_animal AS" in sql
        assert "checked_voluntario AS" in sql
        assert "UPDATE terapias AS target_terapia SET" in sql
        assert "RETURNING" in sql

    def test_params_order(self) -> None:
        _, params = salud_queries.build_update_terapia("t-id", {
            "animal_id": "a-id",
            "voluntario_id": "b-id",
            "fecha": "2026-07-05",
            "descripcion": "new desc",
        })
        assert params == ["t-id", "a-id", "b-id", "2026-07-05", "new desc"]

    def test_params_count(self) -> None:
        sql, params = salud_queries.build_update_terapia("t-id", {
            "animal_id": "a",
            "voluntario_id": "b",
            "fecha": "2026-07-04",
            "descripcion": None,
        })
        assert len(params) == 5
        _assert_params_count(sql, 5)


class TestBuildDeleteTerapia:
    def test_sql_has_pending_check(self) -> None:
        sql, _ = salud_queries.build_delete_terapia("t-id")
        assert "pending_recomendaciones AS" in sql
        assert "completada = false" in sql
        assert "NOT EXISTS (SELECT 1 FROM pending_recomendaciones)" in sql

    def test_params(self) -> None:
        sql, params = salud_queries.build_delete_terapia("t-id")
        assert params == ["t-id"]
        _assert_params_count(sql, 1)


class TestBuildCreateRecomendacion:
    def test_sql_is_cte_with_terapia_check(self) -> None:
        sql, _ = salud_queries.build_create_recomendacion({
            "terapia_id": "t-id",
            "fecha": "2026-07-04",
            "texto": "some text",
        })
        assert "WITH checked_terapia AS" in sql
        assert "INSERT INTO recomendaciones" in sql
        assert "ON DELETE CASCADE" not in sql  # DB-level, not here

    def test_params_order(self) -> None:
        _, params = salud_queries.build_create_recomendacion({
            "terapia_id": "t-id",
            "fecha": "2026-07-04",
            "texto": "Apply ice",
        })
        assert params == ["t-id", "2026-07-04", "Apply ice"]

    def test_params_count(self) -> None:
        sql, params = salud_queries.build_create_recomendacion({
            "terapia_id": "t",
            "fecha": "2026-07-04",
            "texto": "t",
        })
        assert len(params) == 3
        _assert_params_count(sql, 3)


class TestBuildListRecomendacionesByTerapia:
    def test_sql(self) -> None:
        sql, params = salud_queries.build_list_recomendaciones_by_terapia("t-id")
        assert "recomendaciones" in sql
        assert "terapia_id = $1" in sql
        assert "activo = true" in sql
        assert "ORDER BY fecha DESC" in sql
        assert params == ["t-id"]
        _assert_params_count(sql, 1)


class TestBuildCompleteRecomendacion:
    def test_sql_sets_completada_true(self) -> None:
        sql, params = salud_queries.build_complete_recomendacion("r-id")
        assert "SET completada = true" in sql
        assert "WHERE id = $1" in sql
        assert "activo = true" in sql
        assert params == ["r-id"]
        _assert_params_count(sql, 1)

    def test_returns_row(self) -> None:
        sql, _ = salud_queries.build_complete_recomendacion("r-id")
        assert "RETURNING" in sql


class TestBuildDeleteRecomendacion:
    def test_sql_soft_deletes(self) -> None:
        sql, params = salud_queries.build_delete_recomendacion("r-id")
        assert "SET activo = false" in sql
        assert "WHERE id = $1" in sql
        assert params == ["r-id"]
        _assert_params_count(sql, 1)

    def test_returns_id(self) -> None:
        sql, _ = salud_queries.build_delete_recomendacion("r-id")
        assert "RETURNING id" in sql
