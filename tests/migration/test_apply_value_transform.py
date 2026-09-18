"""Direct tests for ``_apply_value_transform`` (migration.apply_helpers).

These tests target each transform in the dispatcher directly, without
the per-row mapping pipeline. The goal is twofold:

1. Make the contract of every transform observable in isolation (the
   legacy ``tests/test_migration.py::test_apply*`` paths only exercise
   a subset — ``identity`` and a few others).
2. Push the per-branch coverage of ``_apply_value_transform`` close to
   100% so the CRAP ratchet stops tripping on this function
   (baseline 23.82; observed 165.41 on ``origin/main`` before this
   slice). See issue #797.

Each transform lives in its own ``Test*`` class so a failure points to
the contract that drifted, not to "somewhere in
``_apply_value_transform``".
"""

from __future__ import annotations

import pytest

from migration.apply_helpers import _apply_value_transform

# ---------- identity ---------------------------------------------------


class TestIdentity:
    """``identity`` is the trivial pass-through used for columns that
    need no transformation between the legacy schema and the web
    schema."""

    def test_returns_value_unchanged_for_string(self) -> None:
        assert _apply_value_transform("identity", "hello") == "hello"

    def test_returns_value_unchanged_for_none(self) -> None:
        assert _apply_value_transform("identity", None) is None

    def test_returns_value_unchanged_for_int(self) -> None:
        assert _apply_value_transform("identity", 42) == 42


# ---------- nullify_empty_string --------------------------------------


class TestNullifyEmptyString:
    """``nullify_empty_string`` maps Access's empty-string convention
    (legacy ``''`` instead of ``NULL``) onto Postgres' NULLABLE columns.
    Without this transform, dates like ``FIMPLANTACIONCHIP=''`` fail
    with "invalid input syntax for type date" (issue #639)."""

    def test_none_stays_none(self) -> None:
        assert _apply_value_transform("nullify_empty_string", None) is None

    def test_empty_string_becomes_none(self) -> None:
        assert _apply_value_transform("nullify_empty_string", "") is None

    def test_whitespace_only_becomes_none(self) -> None:
        assert _apply_value_transform("nullify_empty_string", "   ") is None

    def test_non_empty_string_kept(self) -> None:
        assert _apply_value_transform("nullify_empty_string", "hello") == "hello"

    def test_int_zero_kept(self) -> None:
        # The transform only treats *string* empty values as null.
        assert _apply_value_transform("nullify_empty_string", 0) == 0


# ---------- normalize_sexo --------------------------------------------


class TestNormalizeSexo:
    """``normalize_sexo`` maps the legacy full-word ``Sexo`` column
    (``TbFichaAnimal``: ``Hembra`` / ``Macho``) onto the single-letter
    web code (``animales.sexo``: ``M`` / ``H``). Anything else (None,
    empty, unknown) becomes ``None`` so the apply reports the row as
    a skip rather than a CHECK violation (issue #639)."""

    @pytest.mark.parametrize(
        "raw",
        ["Hembra", "HEMBRA", "H", "h", "Female", "FEMALE", "F", "f"],
    )
    def test_hembra_variants_become_H(self, raw: str) -> None:
        assert _apply_value_transform("normalize_sexo", raw) == "H"

    @pytest.mark.parametrize(
        "raw",
        ["Macho", "MACHO", "M", "m", "Male", "MALE"],
    )
    def test_macho_variants_become_M(self, raw: str) -> None:
        assert _apply_value_transform("normalize_sexo", raw) == "M"

    @pytest.mark.parametrize("raw", ["", "   "])
    def test_blank_becomes_none(self, raw: str) -> None:
        assert _apply_value_transform("normalize_sexo", raw) is None

    def test_none_stays_none(self) -> None:
        assert _apply_value_transform("normalize_sexo", None) is None

    def test_unknown_value_becomes_none(self) -> None:
        # Unknown values fall through to None (skip, not raise).
        assert _apply_value_transform("normalize_sexo", "OTHER") is None


# ---------- normalize_especie -----------------------------------------


class TestNormalizeEspecie:
    """``normalize_especie`` upper-cases the legacy ``Especie`` column
    (``TbFichaAnimal``: ``CANINA`` / ``felina``, mixed case) onto the
    uppercase CHECK constraint of ``animales.especie``. Unknown values
    become ``None`` (issue #639)."""

    @pytest.mark.parametrize("raw", ["CANINA", "canina", "Canina"])
    def test_canina_variants_become_CANINA(self, raw: str) -> None:
        assert _apply_value_transform("normalize_especie", raw) == "CANINA"

    @pytest.mark.parametrize("raw", ["FELINA", "felina", "Felina"])
    def test_felina_variants_become_FELINA(self, raw: str) -> None:
        assert _apply_value_transform("normalize_especie", raw) == "FELINA"

    @pytest.mark.parametrize("raw", ["", "   "])
    def test_blank_becomes_none(self, raw: str) -> None:
        assert _apply_value_transform("normalize_especie", raw) is None

    def test_none_stays_none(self) -> None:
        assert _apply_value_transform("normalize_especie", None) is None

    def test_unknown_value_becomes_none(self) -> None:
        assert _apply_value_transform("normalize_especie", "REPTIL") is None


# ---------- normalize_si_no -------------------------------------------


class TestNormalizeSiNo:
    """``normalize_si_no`` maps legacy ``Sí`` / ``No`` / ``Si`` (with
    or without tilde, mixed case) onto the canonical Spanish ``Sí`` /
    ``No``. The web column is TEXT, but the operator expects the
    canonical form for round-trip comparison."""

    @pytest.mark.parametrize(
        "raw",
        ["Sí", "sí", "Si", "si", "S", "s", "Yes", "yes", "1", "true", "TRUE"],
    )
    def test_yes_variants_become_Si(self, raw: str) -> None:
        assert _apply_value_transform("normalize_si_no", raw) == "Sí"

    @pytest.mark.parametrize(
        "raw",
        ["No", "no", "N", "n", "0", "false", "FALSE"],
    )
    def test_no_variants_become_No(self, raw: str) -> None:
        assert _apply_value_transform("normalize_si_no", raw) == "No"

    @pytest.mark.parametrize("raw", ["", "   "])
    def test_blank_becomes_none(self, raw: str) -> None:
        assert _apply_value_transform("normalize_si_no", raw) is None

    def test_none_stays_none(self) -> None:
        assert _apply_value_transform("normalize_si_no", None) is None

    def test_unknown_value_becomes_none(self) -> None:
        # Unknown values fall through to None (skip, not raise).
        assert _apply_value_transform("normalize_si_no", "MAYBE") is None


# ---------- currency_to_numeric / double_to_numeric ------------------


class TestCurrencyToNumeric:
    """``currency_to_numeric`` and ``double_to_numeric`` are declared
    in the design but currently pass through (the mapping uses
    ``identity`` in practice). They are documented future home."""

    def test_currency_returns_value_unchanged(self) -> None:
        assert _apply_value_transform("currency_to_numeric", "12,34 €") == "12,34 €"

    def test_double_returns_value_unchanged(self) -> None:
        assert _apply_value_transform("double_to_numeric", "3.14") == "3.14"


# ---------- defaults / fk_lookup --------------------------------------


class TestDefaultsAndFkLookup:
    """``default_now`` / ``default_uuid`` / ``default_true`` and
    ``fk_lookup`` are web-only / FK paths that the legacy-row path
    never reaches. The dispatcher falls through with identity for
    safety."""

    @pytest.mark.parametrize(
        "transform",
        ["default_now", "default_uuid", "default_true", "fk_lookup"],
    )
    def test_defaults_return_value(self, transform: str) -> None:
        assert _apply_value_transform(transform, "anything") == "anything"

    @pytest.mark.parametrize(
        "transform",
        ["default_now", "default_uuid", "default_true", "fk_lookup"],
    )
    def test_defaults_return_none(self, transform: str) -> None:
        assert _apply_value_transform(transform, None) is None


# ---------- unknown transform -----------------------------------------


class TestUnknownTransform:
    """Unknown transform names pass through. The ``Literal`` type in
    ``ColumnMapping`` prevents this at validation time, but a
    defensive fallback is cheap."""

    def test_unknown_returns_value_unchanged(self) -> None:
        # The defensive fallback should never raise; this test pins
        # that contract even though the type system forbids it.
        assert _apply_value_transform("not_a_real_transform", "hello") == "hello"

    def test_unknown_returns_none_unchanged(self) -> None:
        assert _apply_value_transform("not_a_real_transform", None) is None
