"""Regression tests for the optional death date in the shared animal form."""

from app.modules.animals.forms import AnimalForm

_REQUIRED_FORM_DATA = {
    "NCHIP": "123456789012345",
    "NombreAnimal": "Luna",
    "Especie": "CANINA",
    "Sexo": "H",
    "FNacimiento": "2023-04-12",
    "Terapia": "No",
    "TraeNChip": "No",
    "FIMPLANTACIONCHIP": "2023-04-12",
    "NombreFoto": "luna.jpg",
}


def test_blank_optional_death_date_becomes_none() -> None:
    form = AnimalForm.model_validate({**_REQUIRED_FORM_DATA, "FDefuncion": ""})

    assert form.FDefuncion is None


def test_nonblank_optional_death_date_is_unchanged() -> None:
    form = AnimalForm.model_validate(
        {**_REQUIRED_FORM_DATA, "FDefuncion": "2025-01-30"}
    )

    assert form.FDefuncion == "2025-01-30"
