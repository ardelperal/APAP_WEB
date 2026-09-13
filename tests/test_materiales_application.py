"""Application-layer tests for the materiales use cases (issue #752, PR 3 of 5).

Mirrors the stub-port pattern from
``tests/test_animals_application_*.py`` so the use-case tests stay
transport-free: the application code never sees
``LocalPostgresExecutor`` or ``SqlExecutor``; it talks to the
:class:`MaterialesPort` Protocol only.

The eight use cases (one per port method) own the validation policy
the legacy ``service.py`` exported, but the FK checks (estancia open
+ active, material active) are NOT a database query the application
makes — they are two new Protocol methods the adapter implements.
This keeps ``application/`` 100% free of SQL while the use cases
keep rejecting inactive / closed stays (Scenario 8 in spec #15894).
"""

from __future__ import annotations

import pytest

from app.modules.materiales.application.assign_material_to_estancia import (
    assign_material_to_estancia,
)
from app.modules.materiales.application.create_material import (
    MaterialValidationError,
    create_material,
)
from app.modules.materiales.application.deactivate_material import (
    deactivate_material,
)
from app.modules.materiales.application.get_material_by_id import (
    get_material_by_id,
)
from app.modules.materiales.application.list_materials import (
    list_materials,
)
from app.modules.materiales.application.list_materials_for_estancia import (
    list_materials_for_estancia,
)
from app.modules.materiales.application.remove_material_from_estancia import (
    remove_material_from_estancia,
)
from app.modules.materiales.application.update_material import (
    update_material,
)
from app.modules.materiales.domain.estancia_material import EstanciaMaterial
from app.modules.materiales.domain.material import Material

# --- stub port --------------------------------------------------------------


class _StubPort:
    """Stub implementation of :class:`MaterialesPort` for unit tests.

    The stub is the *single* source of truth the use cases see: every
    assertion checks that the right method was called with the right
    arguments and that the returned dataclass is what the use case
    forwarded. The stub records the FK-check calls separately so a
    regression where ``assign_material_to_estancia`` skips the
    estancia/material liveness probe fails this suite.
    """

    def __init__(self) -> None:
        # catalog CRUD
        self.last_create_params: dict | None = None
        self.last_update_id: str | None = None
        self.last_update_params: dict | None = None
        self.last_deactivate_id: str | None = None
        self.last_get_id: str | None = None
        self.last_list_activos: bool | None = None
        # junction CRUD
        self.last_assign_estancia: str | None = None
        self.last_assign_material: str | None = None
        self.last_assign_cantidad: int | None = None
        self.last_assign_notas: str | None = None
        self.last_list_for_estancia_id: str | None = None
        self.last_list_for_estancia_activos: bool | None = None
        self.last_remove_junction_id: str | None = None
        # FK check probes — configurable so tests can simulate inactive
        # estancia / inactive material without monkey-patching the method
        # (a method-replace would lose the call-recording side effect).
        self.estancia_open_calls: list[str] = []
        self.material_active_calls: list[str] = []
        self.estancia_is_open_and_active_flag: bool = True
        self.material_is_active_flag: bool = True
        # response queue
        self.next_material: Material | None = None
        self.next_materials: list[Material] | None = None
        self.next_junction: EstanciaMaterial | None = None
        self.next_junctions: list[EstanciaMaterial] | None = None
        self.next_deactivate_flag: bool = False
        self.next_remove_flag: bool = False

    # --- port surface (only the eight + two FK probes the use cases call) ---

    def create_material(self, params: dict) -> Material:
        self.last_create_params = params
        if self.next_material is None:
            raise AssertionError("stub next_material unset")
        return self.next_material

    def get_material_by_id(self, material_id: str) -> Material | None:
        self.last_get_id = material_id
        return self.next_material

    def list_materials(self, activos_solo: bool = True) -> list[Material]:
        self.last_list_activos = activos_solo
        return list(self.next_materials or [])

    def update_material(
        self, material_id: str, params: dict
    ) -> Material | None:
        self.last_update_id = material_id
        self.last_update_params = params
        return self.next_material

    def deactivate_material(self, material_id: str) -> bool:
        self.last_deactivate_id = material_id
        return self.next_deactivate_flag

    def assign_material_to_estancia(
        self,
        estancia_id: str,
        material_id: str,
        cantidad: int = 1,
        notas: str | None = None,
    ) -> EstanciaMaterial:
        self.last_assign_estancia = estancia_id
        self.last_assign_material = material_id
        self.last_assign_cantidad = cantidad
        self.last_assign_notas = notas
        if self.next_junction is None:
            raise AssertionError("stub next_junction unset")
        return self.next_junction

    def list_materials_for_estancia(
        self, estancia_id: str, activos_solo: bool = True
    ) -> list[EstanciaMaterial]:
        self.last_list_for_estancia_id = estancia_id
        self.last_list_for_estancia_activos = activos_solo
        return list(self.next_junctions or [])

    def remove_material_from_estancia(self, junction_id: str) -> bool:
        self.last_remove_junction_id = junction_id
        return self.next_remove_flag

    # --- FK probes (new in PR 3) --------------------------------------------

    def estancia_is_open_and_active(self, estancia_id: str) -> bool:
        self.estancia_open_calls.append(estancia_id)
        return self.estancia_is_open_and_active_flag

    def material_is_active(self, material_id: str) -> bool:
        self.material_active_calls.append(material_id)
        return self.material_is_active_flag


# --- fixtures ---------------------------------------------------------------


def _material() -> Material:
    return Material(
        id="00000000-0000-0000-0000-000000000001",
        material="Manta",
        tamano="M",
        color="azul",
    )


def _junction() -> EstanciaMaterial:
    return EstanciaMaterial(
        id="00000000-0000-0000-0000-000000000010",
        estancia_id="00000000-0000-0000-0000-000000000002",
        material_id="00000000-0000-0000-0000-000000000001",
        cantidad=2,
    )


# --- create_material --------------------------------------------------------


def test_create_material_strips_required_text_and_delegates() -> None:
    """Blank-padded required text is stripped before the port sees it."""
    port = _StubPort()
    port.next_material = _material()

    result = create_material(
        port,
        material=" Manta ",
        tamano=" M ",
        color=" azul ",
        observaciones="  test  ",
    )

    assert result is port.next_material
    assert port.last_create_params == {
        "material": "Manta",
        "tamano": "M",
        "color": "azul",
        "observaciones": "test",
    }


def test_create_material_blank_material_raises_before_touching_port() -> None:
    port = _StubPort()
    port.next_material = _material()

    for blank in ("", "   ", "\t\n"):
        with pytest.raises(MaterialValidationError, match="material"):
            create_material(
                port, material=blank, tamano="M", color="azul"
            )

    assert port.last_create_params is None


def test_create_material_blank_tamano_raises_before_touching_port() -> None:
    port = _StubPort()
    port.next_material = _material()

    with pytest.raises(MaterialValidationError, match="tamano"):
        create_material(port, material="Manta", tamano="", color="azul")
    assert port.last_create_params is None


def test_create_material_blank_color_raises_before_touching_port() -> None:
    port = _StubPort()
    port.next_material = _material()

    with pytest.raises(MaterialValidationError, match="color"):
        create_material(port, material="Manta", tamano="M", color="")
    assert port.last_create_params is None


def test_create_material_validation_error_subclasses_value_error() -> None:
    """Legacy ``except ValueError`` clauses keep working."""
    assert issubclass(MaterialValidationError, ValueError)


def test_create_material_optional_observaciones_pass_through() -> None:
    """``observaciones`` is optional; ``None`` and blank-string both pass."""
    port = _StubPort()
    port.next_material = _material()

    create_material(
        port, material="Manta", tamano="M", color="azul", observaciones=None
    )
    assert port.last_create_params is not None
    assert port.last_create_params["observaciones"] is None


# --- get_material_by_id -----------------------------------------------------


def test_get_material_by_id_passes_id_through() -> None:
    port = _StubPort()
    port.next_material = _material()

    result = get_material_by_id(port, "00000000-0000-0000-0000-000000000001")

    assert result is port.next_material
    assert port.last_get_id == "00000000-0000-0000-0000-000000000001"


def test_get_material_by_id_returns_none_when_port_returns_none() -> None:
    port = _StubPort()
    port.next_material = None

    assert get_material_by_id(port, "x") is None


# --- list_materials ---------------------------------------------------------


def test_list_materials_defaults_to_activos_only() -> None:
    port = _StubPort()
    port.next_materials = [_material()]

    result = list_materials(port)

    assert result == [_material()]
    assert port.last_list_activos is True


def test_list_materials_includes_inactive_when_requested() -> None:
    port = _StubPort()
    port.next_materials = [_material()]

    list_materials(port, activos_solo=False)

    assert port.last_list_activos is False


# --- update_material --------------------------------------------------------


def test_update_material_strips_text_and_delegates() -> None:
    port = _StubPort()
    port.next_material = _material()

    result = update_material(
        port,
        "00000000-0000-0000-0000-000000000001",
        material=" Manta ", observaciones="  test  ",
    )

    assert result is port.next_material
    assert port.last_update_id == "00000000-0000-0000-0000-000000000001"
    assert port.last_update_params == {
        "material": "Manta",
        "observaciones": "test",
    }


def test_update_material_blank_text_raises_before_touching_port() -> None:
    port = _StubPort()
    port.next_material = _material()

    with pytest.raises(MaterialValidationError, match="material"):
        update_material(
            port,
            "00000000-0000-0000-0000-000000000001",
            material="",
        )
    assert port.last_update_params is None


def test_update_material_no_kwargs_raises_before_touching_port() -> None:
    """Calling ``update_material`` with no field kwargs is a no-op error."""
    port = _StubPort()
    port.next_material = _material()

    with pytest.raises(MaterialValidationError, match="al menos un campo"):
        update_material(
            port, "00000000-0000-0000-0000-000000000001"
        )
    assert port.last_update_params is None


def test_update_material_returns_none_when_port_returns_none() -> None:
    port = _StubPort()
    port.next_material = None

    assert update_material(
        port, "x", material="Manta"
    ) is None


# --- deactivate_material ----------------------------------------------------


def test_deactivate_material_returns_port_flag() -> None:
    port = _StubPort()
    port.next_deactivate_flag = True

    assert deactivate_material(port, "00000000-0000-0000-0000-000000000001") is True
    assert port.last_deactivate_id == "00000000-0000-0000-0000-000000000001"


# --- assign_material_to_estancia -------------------------------------------


def test_assign_probes_estancia_and_material_before_inserting() -> None:
    """The FK probes run before any delegation to the port INSERT path."""
    port = _StubPort()
    port.next_junction = _junction()

    result = assign_material_to_estancia(
        port,
        estancia_id="00000000-0000-0000-0000-000000000002",
        material_id="00000000-0000-0000-0000-000000000001",
        cantidad=3,
        notas="entrega parcial",
    )

    assert result is port.next_junction
    assert port.estancia_open_calls == [
        "00000000-0000-0000-0000-000000000002"
    ]
    assert port.material_active_calls == [
        "00000000-0000-0000-0000-000000000001"
    ]
    assert port.last_assign_estancia == "00000000-0000-0000-0000-000000000002"
    assert port.last_assign_material == "00000000-0000-0000-0000-000000000001"
    assert port.last_assign_cantidad == 3
    assert port.last_assign_notas == "entrega parcial"


def test_assign_rejects_closed_estancia_without_inserting() -> None:
    port = _StubPort()
    port.estancia_is_open_and_active_flag = False
    port.next_junction = _junction()

    with pytest.raises(MaterialValidationError, match="estancia"):
        assign_material_to_estancia(
            port,
            estancia_id="00000000-0000-0000-0000-000000000002",
            material_id="00000000-0000-0000-0000-000000000001",
        )

    assert port.estancia_open_calls == [
        "00000000-0000-0000-0000-000000000002"
    ]
    assert port.material_active_calls == [], (
        "material probe must not run when estancia probe fails"
    )
    assert port.last_assign_estancia is None, (
        "assign must short-circuit before the port INSERT is invoked"
    )


def test_assign_rejects_inactive_material_without_inserting() -> None:
    port = _StubPort()
    port.material_is_active_flag = False
    port.next_junction = _junction()

    with pytest.raises(MaterialValidationError, match="material"):
        assign_material_to_estancia(
            port,
            estancia_id="00000000-0000-0000-0000-000000000002",
            material_id="00000000-0000-0000-0000-000000000001",
        )

    assert port.material_active_calls == [
        "00000000-0000-0000-0000-000000000001"
    ]
    assert port.last_assign_material is None


def test_assign_defaults_cantidad_to_one_and_notas_to_none() -> None:
    port = _StubPort()
    port.next_junction = _junction()

    assign_material_to_estancia(
        port,
        estancia_id="00000000-0000-0000-0000-000000000002",
        material_id="00000000-0000-0000-0000-000000000001",
    )

    assert port.last_assign_cantidad == 1
    assert port.last_assign_notas is None


# --- list_materials_for_estancia -------------------------------------------


def test_list_for_estancia_defaults_to_activos_only() -> None:
    port = _StubPort()
    port.next_junctions = [_junction()]

    result = list_materials_for_estancia(
        port, "00000000-0000-0000-0000-000000000002"
    )

    assert result == [_junction()]
    assert port.last_list_for_estancia_id == "00000000-0000-0000-0000-000000000002"
    assert port.last_list_for_estancia_activos is True


def test_list_for_estancia_includes_inactive_when_requested() -> None:
    port = _StubPort()
    port.next_junctions = [_junction()]

    list_materials_for_estancia(
        port, "00000000-0000-0000-0000-000000000002", activos_solo=False
    )

    assert port.last_list_for_estancia_activos is False


# --- remove_material_from_estancia -----------------------------------------


def test_remove_returns_port_flag() -> None:
    port = _StubPort()
    port.next_remove_flag = True

    assert remove_material_from_estancia(
        port, "00000000-0000-0000-0000-000000000010"
    ) is True
    assert (
        port.last_remove_junction_id
        == "00000000-0000-0000-0000-000000000010"
    )


# NOTE: a port-method-set equality pin already lives in
# tests/test_slice_materiales_architecture.py::test_port_exposes_eight_use_case_methods_plus_two_probes
# and tests/test_materiales_adapter_architecture.py::test_adapter_exposes_exactly_ten_public_methods
# — duplicating it here would be parallel prose (AI-slop signature #1).
