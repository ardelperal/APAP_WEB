"""Builder-contract tests for ``app.modules.animals.queries``.

Per AGENTS.md §22, the SQL/service separation seam requires SQL strings
and parameter shaping to live in a dedicated ``queries.py`` per feature
module. The builder contract is the testable surface — these tests
prove the builders return well-formed ``(sql, params)`` tuples without
needing transport, InsForge, or HTTP.

Issue #435 — ``app/modules/animals/queries.py`` is the highest-density
queries module in the project (238 LOC, 65 mutable AST sites,
27.3 sites / 100 LOC) and previously had zero dedicated builder tests.
The suite below pins every public builder, the ``DB_LABEL_TO_ESTADO``
reverse mapping, and ``AnimalSearchParams.cap_limit`` so a typo in any
of them fails FAST, before the integration tests fail more opaquely.

The seam is symmetric with the existing builder tests in
``tests/test_acogidas_queries.py`` and ``tests/test_<slice>_queries.py``
across the project. Once this lands, ``app/modules/animals/queries.py``
becomes a mutation-gate candidate (per #434 / Step 5 of the hardening
roadmap).
"""

from __future__ import annotations

import pytest

from app.modules.animals import queries

# ---------------------------------------------------------------------------
# DB_LABEL_TO_ESTADO — reverse mapping (DB Spanish label → API snake_case)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("db_label", "api_estado"),
    [
        ("Pendiente de Entrada", "pendiente_entrada"),
        ("Pendiente de Nueva Situación", "pendiente_nueva_situacion"),
        ("Albergue", "albergue"),
        ("Acogida", "acogida"),
        ("Adoptado", "adoptado"),
        ("Entregado", "entregado"),
        ("Fallecido (Albergue)", "fallecido_albergue"),
        ("Fallecido (Acogida)", "fallecido_acogida"),
        ("Fallecido (Adoptado)", "fallecido_adoptado"),
        ("Fallecido (Entregado)", "fallecido_entregado"),
        ("Fallecido (Desconocido)", "fallecido_desconocido"),
        ("Incoherente", "incoherente"),
    ],
)
def test_db_label_to_estado_round_trips_every_mapped_label(
    db_label: str, api_estado: str
) -> None:
    """Every DB Spanish label maps back to its API snake_case estado.

    This is the reverse mapping used by ``_db_state_to_api_estado`` in
    ``app.modules.animals.service`` to normalize rows coming from the
    ``animal_current_state`` view (LIFECYCLE-02 / issue #69). A typo
    on either side of the round-trip silently corrupts the search
    response.
    """
    assert queries.DB_LABEL_TO_ESTADO[db_label] == api_estado


# ---------------------------------------------------------------------------
# DB_LABEL_TO_ESTADO — pin tests for LIFECYCLE-03 PR-C
# ---------------------------------------------------------------------------
# These pin the corrected (canonical accented, 5-variant Fallecido) spelling
# after the defect fix in C4. Both tests FAIL today — the current spelling
# at ``app/modules/animals/queries.py:45`` is accent-less and the
# ``fallecido`` key is collapsed to ``"Fallecido (Albergue)"`` for every
# death. The pin below is what the cascade (PR-A) writes to
# ``animal_current_state.current_state`` and what the CHECK constraint at
# ``app/core/domain_lifecycle.py:147-156`` allows.


def test_db_label_to_estado_uses_accented_pendiente_nueva_situacion() -> None:
    """Pin #9: ``_ESTADO_DB_LABEL['pendiente_nueva_situacion']`` carries
    the accented ``"Pendiente de Nueva Situación"`` (with acute) — the
    canonical form enforced by the ``animal_current_state`` CHECK constraint
    and the cascade output. Mirrors ``migration/derivation.py:62``.
    """
    assert queries._ESTADO_DB_LABEL["pendiente_nueva_situacion"] == (
        "Pendiente de Nueva Situación"
    )


def test_db_label_to_estado_lists_all_fallecido_variants() -> None:
    """Pin #10: the 5 ``Fallecido (X)`` CHECK-allowed variants each map
    to their own API key (``fallecido_albergue``, ``fallecido_acogida``,
    ``fallecido_adoptado``, ``fallecido_entregado``, ``fallecido_desconocido``).
    The previous collapsed ``fallecido`` key only carried
    ``"Fallecido (Albergue)"`` — a fidelity bug.
    """
    expected_variants = {
        "fallecido_albergue": "Fallecido (Albergue)",
        "fallecido_acogida": "Fallecido (Acogida)",
        "fallecido_adoptado": "Fallecido (Adoptado)",
        "fallecido_entregado": "Fallecido (Entregado)",
        "fallecido_desconocido": "Fallecido (Desconocido)",
    }
    for api_key, db_label in expected_variants.items():
        assert queries._ESTADO_DB_LABEL[api_key] == db_label, (
            f"_ESTADO_DB_LABEL[{api_key!r}] must be {db_label!r}; "
            f"got {queries._ESTADO_DB_LABEL.get(api_key)!r}"
        )
    # The legacy collapsed key must NOT exist any more — the bug being fixed.
    assert "fallecido" not in queries._ESTADO_DB_LABEL, (
        "Collapsed 'fallecido' key is the P1 fidelity bug; use the 5 "
        "variant keys (fallecido_albergue, ..., fallecido_desconocido)"
    )


def test_db_label_to_estado_returns_none_for_unmapped_label() -> None:
    """Unknown DB labels must NOT silently coerce to a real estado.

    ``dict.get`` returns ``None`` on miss; the service layer maps that
    to ``"incoherente"`` (see ``_db_state_to_api_estado``). The builder
    itself must surface ``None`` so the service owns the fallback rule
    — that single source of truth is what AGENTS.md §4 requires.
    """
    assert queries.DB_LABEL_TO_ESTADO.get("Estado Inexistente") is None
    assert queries.DB_LABEL_TO_ESTADO.get("") is None


def test_valid_estados_matches_db_label_mapping_keys() -> None:
    """``VALID_ESTADOS`` mirrors the API-side mapping keys (AGENTS.md §4).

    ``VALID_ESTADOS`` is derived from the same dict the reverse map is
    built from, so adding a label requires no second list. This test
    pins that single-source-of-truth invariant. The 5 ``fallecido_<x>``
    variants are exposed as separate API keys after the LIFECYCLE-03
    PR-C defect fix (C4) so REPORT-05 dashboard counters see every
    pre-death state individually instead of collapsed to one.
    """
    assert queries.VALID_ESTADOS == frozenset(
        {
            "pendiente_entrada",
            "pendiente_nueva_situacion",
            "albergue",
            "acogida",
            "adoptado",
            "entregado",
            "fallecido_albergue",
            "fallecido_acogida",
            "fallecido_adoptado",
            "fallecido_entregado",
            "fallecido_desconocido",
            "incoherente",
        }
    )


# ---------------------------------------------------------------------------
# AnimalSearchParams.cap_limit
# ---------------------------------------------------------------------------


def test_cap_limit_returns_self_when_within_cap() -> None:
    """``limit <= 200`` is returned unchanged (no copy)."""
    params = queries.AnimalSearchParams(limit=50)
    assert params.cap_limit() is params


def test_cap_limit_returns_self_at_exact_boundary() -> None:
    """``limit == 200`` is the boundary; stays as-is."""
    params = queries.AnimalSearchParams(limit=200)
    assert params.cap_limit() is params


def test_cap_limit_caps_above_200() -> None:
    """``limit > 200`` is capped to 200; other fields preserved."""
    params = queries.AnimalSearchParams(limit=500, offset=10)
    capped = params.cap_limit()
    assert capped.limit == 200
    assert capped.offset == 10
    # Capped value is a fresh instance (frozen dataclass replace)
    assert capped is not params


# ---------------------------------------------------------------------------
# build_animal_search — default + happy path
# ---------------------------------------------------------------------------


def test_build_animal_search_default_emits_full_select() -> None:
    """No filters: SELECT list + JOIN + WHERE activo + ORDER BY + LIMIT/OFFSET.

    Pins the SQL template literally so a typo in the JOIN, the column
    list, or the ORDER BY clause fails here, not in integration tests.
    """
    sql, params = queries.build_animal_search(queries.AnimalSearchParams())

    expected_sql = (
        "SELECT a.id, a.NCHIP, a.NombreAnimal, a.Especie, a.Sexo, "
        "a.FNacimiento, a.fecha_alta, a.activo, acs.current_state "
        "FROM animales a "
        "LEFT JOIN animal_current_state acs ON a.id = acs.animal_id "
        "WHERE a.activo = true "
        "ORDER BY a.fecha_alta DESC "
        "LIMIT $1 OFFSET $2"
    )
    assert sql == expected_sql
    # Only LIMIT/OFFSET appear in params (no filter values).
    assert params == [50, 0]


# ---------------------------------------------------------------------------
# build_animal_search — dynamic filter paths (issue #435 calls these out)
# ---------------------------------------------------------------------------


def test_build_animal_search_chip_only_uses_exact_match() -> None:
    """``chip`` is the natural-key exact match; the chip value becomes $1."""
    sql, params = queries.build_animal_search(
        queries.AnimalSearchParams(chip="941000000000001")
    )
    assert "AND a.NCHIP = $1" in sql
    # q is not present, so no ILIKE clause
    assert "ILIKE" not in sql
    assert params == ["941000000000001", 50, 0]


def test_build_animal_search_q_only_uses_ilike_substring() -> None:
    """``q`` is a substring match on ``NombreAnimal`` (case-insensitive).

    The builder wraps the value in ``%`` so the caller passes the raw
    token, not a pre-wrapped pattern. Pinning the wrap prevents the
    builder from silently changing the contract.
    """
    sql, params = queries.build_animal_search(
        queries.AnimalSearchParams(q="Rex")
    )
    assert "AND a.NombreAnimal ILIKE $1" in sql
    # No NCHIP filter — ``a.NCHIP`` appears in the SELECT list, so we
    # pin the filter placeholder (``a.NCHIP = $N``) instead.
    assert "a.NCHIP = $" not in sql
    assert params == ["%Rex%", 50, 0]


def test_build_animal_search_chip_takes_precedence_over_q() -> None:
    """``chip`` exact match wins; ``q`` is dropped from the WHERE clause.

    The chip-and-q combination must not emit both ``NCHIP = $N`` and
    ``ILIKE $N`` simultaneously — the chip path is the natural-key
    match and ``ILIKE`` would over-fetch rows the chip query already
    identified exactly.
    """
    sql, params = queries.build_animal_search(
        queries.AnimalSearchParams(chip="941000000000001", q="Rex")
    )
    assert "AND a.NCHIP = $1" in sql
    assert "ILIKE" not in sql
    # Only the chip value flows through as a filter param.
    assert params == ["941000000000001", 50, 0]


def test_build_animal_search_especie_only() -> None:
    """``especie`` exact match against ``a.Especie``."""
    sql, params = queries.build_animal_search(
        queries.AnimalSearchParams(especie="CANINA")
    )
    assert "AND a.Especie = $1" in sql
    assert params == ["CANINA", 50, 0]


def test_build_animal_search_sexo_only() -> None:
    """``sexo`` exact match against ``a.Sexo``."""
    sql, params = queries.build_animal_search(
        queries.AnimalSearchParams(sexo="M")
    )
    assert "AND a.Sexo = $1" in sql
    assert params == ["M", 50, 0]


def test_build_animal_search_estado_mapped_to_db_label() -> None:
    """``estado`` API value is translated to the DB Spanish label.

    ``albergue`` (API snake_case) becomes ``Albergue`` (DB label) and
    is bound against ``acs.current_state``, not ``a.<column>``. This is
    the single-source-of-truth mapping from AGENTS.md §4.
    """
    sql, params = queries.build_animal_search(
        queries.AnimalSearchParams(estado="albergue")
    )
    assert "AND acs.current_state = $1" in sql
    assert params == ["Albergue", 50, 0]


def test_build_animal_search_estado_unmapped_is_silently_dropped() -> None:
    """Unknown ``estado`` API value adds NO clause and NO param.

    An unmapped estado (``_ESTADO_DB_LABEL.get`` returns ``None``) must
    NOT crash and must NOT inject ``NULL = $N`` (which would always be
    false). The filter is silently dropped; the count-builder does the
    same. Service-layer validation catches bad estados before the
    builder ever sees them.
    """
    sql, params = queries.build_animal_search(
        queries.AnimalSearchParams(estado="not_a_real_estado")
    )
    # ``acs.current_state`` is in the SELECT list + JOIN clause; the
    # filter form is ``acs.current_state = $N``. Assert the filter is
    # absent, not just the bare column reference.
    assert "acs.current_state = $" not in sql
    # Only LIMIT/OFFSET, no leaked NULL param.
    assert params == [50, 0]


def test_build_animal_search_fecha_alta_since_only() -> None:
    """``fecha_alta_since`` produces ``>=`` against ``a.fecha_alta``."""
    sql, params = queries.build_animal_search(
        queries.AnimalSearchParams(fecha_alta_since="2026-01-01")
    )
    assert "AND a.fecha_alta >= $1" in sql
    assert "a.fecha_alta <=" not in sql
    assert params == ["2026-01-01", 50, 0]


def test_build_animal_search_fecha_alta_until_only() -> None:
    """``fecha_alta_until`` produces ``<=`` against ``a.fecha_alta``."""
    sql, params = queries.build_animal_search(
        queries.AnimalSearchParams(fecha_alta_until="2026-12-31")
    )
    assert "AND a.fecha_alta <= $1" in sql
    assert "a.fecha_alta >=" not in sql
    assert params == ["2026-12-31", 50, 0]


def test_build_animal_search_fecha_range_combined() -> None:
    """Both bounds emit ``>= $N AND <= $M`` in field-declaration order."""
    sql, params = queries.build_animal_search(
        queries.AnimalSearchParams(
            fecha_alta_since="2026-01-01", fecha_alta_until="2026-12-31"
        )
    )
    assert "AND a.fecha_alta >= $1 AND a.fecha_alta <= $2" in sql
    assert params == ["2026-01-01", "2026-12-31", 50, 0]


# ---------------------------------------------------------------------------
# build_animal_search — combined filters (param-order contract)
# ---------------------------------------------------------------------------


def test_build_animal_search_combined_filters_pin_param_order() -> None:
    """All filters at once: filter params follow filter-declaration order,
    then LIMIT, then OFFSET. The $N indexes in the SQL track the params.

    Declaration order in the builder: chip, q (skipped when chip), especie,
    sexo, estado (mapped), fecha_alta_since, fecha_alta_until. Using
    ``chip`` (not ``q``) so the chip wins and the param list stays
    predictable.
    """
    sql, params = queries.build_animal_search(
        queries.AnimalSearchParams(
            chip="941000000000001",
            especie="CANINA",
            sexo="H",
            estado="acogida",
            fecha_alta_since="2026-01-01",
            fecha_alta_until="2026-12-31",
            limit=10,
            offset=20,
        )
    )
    # WHERE clause: activo, chip, especie, sexo, estado, since, until
    assert (
        "WHERE a.activo = true "
        "AND a.NCHIP = $1 "
        "AND a.Especie = $2 "
        "AND a.Sexo = $3 "
        "AND acs.current_state = $4 "
        "AND a.fecha_alta >= $5 "
        "AND a.fecha_alta <= $6 "
    ) in sql
    # Seven filter values, then LIMIT, then OFFSET.
    assert params == [
        "941000000000001",
        "CANINA",
        "H",
        "Acogida",
        "2026-01-01",
        "2026-12-31",
        10,
        20,
    ]


# ---------------------------------------------------------------------------
# build_animal_search — pagination + limit semantics
# ---------------------------------------------------------------------------


def test_build_animal_search_limit_zero_emits_count_only_sql() -> None:
    """``limit=0`` signals count-only — SELECT COUNT(*), no LIMIT/OFFSET.

    The caller (service layer) treats ``limit=0`` as a count request:
    skips the data query and returns only the total. The builder
    collapses to a single ``SELECT COUNT(*) AS total`` without the
    SELECT-list and pagination clauses.
    """
    sql, params = queries.build_animal_search(
        queries.AnimalSearchParams(limit=0)
    )
    assert sql.startswith("SELECT COUNT(*) AS total ")
    assert "LEFT JOIN animal_current_state acs ON a.id = acs.animal_id" in sql
    assert "WHERE a.activo = true" in sql
    # No LIMIT/OFFSET in count-only mode.
    assert "LIMIT $" not in sql
    assert "OFFSET $" not in sql
    assert params == []


def test_build_animal_search_limit_above_200_is_capped() -> None:
    """``limit > 200`` is capped to 200 by ``cap_limit`` before LIMIT binding."""
    sql, params = queries.build_animal_search(
        queries.AnimalSearchParams(limit=500)
    )
    assert "LIMIT $1 OFFSET $2" in sql
    assert params == [200, 0]


def test_build_animal_search_offset_nonzero() -> None:
    """Non-zero offset flows through to the second LIMIT placeholder."""
    sql, params = queries.build_animal_search(
        queries.AnimalSearchParams(limit=25, offset=100)
    )
    assert "LIMIT $1 OFFSET $2" in sql
    assert params == [25, 100]


# ---------------------------------------------------------------------------
# build_animal_count — count-only builder (paired with limit > 0 path)
# ---------------------------------------------------------------------------


def test_build_animal_count_default_emits_count_only() -> None:
    """Default state: SELECT COUNT(*) with no filter params."""
    sql, params = queries.build_animal_count(queries.AnimalSearchParams())

    expected_sql = (
        "SELECT COUNT(*) AS total "
        "FROM animales a "
        "LEFT JOIN animal_current_state acs ON a.id = acs.animal_id "
        "WHERE a.activo = true"
    )
    assert sql == expected_sql
    assert params == []


def test_build_animal_count_chip_only() -> None:
    """``chip`` adds the NCHIP condition to the count query."""
    sql, params = queries.build_animal_count(
        queries.AnimalSearchParams(chip="941000000000001")
    )
    assert "AND a.NCHIP = $1" in sql
    assert params == ["941000000000001"]


def test_build_animal_count_q_only() -> None:
    """``q`` adds the ILIKE substring condition; value is wrapped in ``%``."""
    sql, params = queries.build_animal_count(
        queries.AnimalSearchParams(q="Luna")
    )
    assert "AND a.NombreAnimal ILIKE $1" in sql
    assert params == ["%Luna%"]


def test_build_animal_count_estado_mapped_to_db_label() -> None:
    """``estado`` API value is translated to the DB Spanish label."""
    sql, params = queries.build_animal_count(
        queries.AnimalSearchParams(estado="adoptado")
    )
    assert "AND acs.current_state = $1" in sql
    assert params == ["Adoptado"]


def test_build_animal_count_estado_unmapped_is_silently_dropped() -> None:
    """Unknown estado in count builder drops the clause and the param."""
    sql, params = queries.build_animal_count(
        queries.AnimalSearchParams(estado="not_a_real_estado")
    )
    assert "acs.current_state" not in sql
    assert params == []


def test_build_animal_count_fecha_range_combined() -> None:
    """``since`` + ``until`` flow in declaration order."""
    sql, params = queries.build_animal_count(
        queries.AnimalSearchParams(
            fecha_alta_since="2026-01-01", fecha_alta_until="2026-12-31"
        )
    )
    assert "AND a.fecha_alta >= $1 AND a.fecha_alta <= $2" in sql
    assert params == ["2026-01-01", "2026-12-31"]


def test_build_animal_count_combined_filters_pin_param_order() -> None:
    """All filters at once: chip wins over q, then especie, sexo, estado,
    fecha bounds. No LIMIT/OFFSET — this is the count path.
    """
    sql, params = queries.build_animal_count(
        queries.AnimalSearchParams(
            chip="941000000000001",
            especie="FELINA",
            sexo="H",
            estado="fallecido_albergue",
            fecha_alta_since="2026-01-01",
            fecha_alta_until="2026-12-31",
        )
    )
    assert (
        "WHERE a.activo = true "
        "AND a.NCHIP = $1 "
        "AND a.Especie = $2 "
        "AND a.Sexo = $3 "
        "AND acs.current_state = $4 "
        "AND a.fecha_alta >= $5 "
        "AND a.fecha_alta <= $6"
    ) in sql
    assert params == [
        "941000000000001",
        "FELINA",
        "H",
        "Fallecido (Albergue)",
        "2026-01-01",
        "2026-12-31",
    ]


def test_build_animal_count_ignores_limit_and_offset() -> None:
    """Count builder never emits LIMIT/OFFSET regardless of limit value."""
    sql, params = queries.build_animal_count(
        queries.AnimalSearchParams(limit=0, offset=0)
    )
    assert "LIMIT" not in sql
    assert "OFFSET" not in sql
    assert params == []
