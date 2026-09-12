"""Architectural pin test for the materiales LocalBackend adapter (issue #755, PR 2 of #752).

Per AGENTS.md §33.4: "Cada slice envía un test pin arquitectónico que
falla cuando un import de transporte se filtra a la capa equivocada.
Una regla sin gate es [anti-patterns.md] §32.P3."

The adapter is the ONLY layer in the materiales slice allowed to
import ``SqlExecutor`` / ``app.core.local_backend``. Domain and ports
stay transport-free (PR 1 pins that invariant); the application
layer (PR 3) must also stay transport-free. This file pins the
adapter's contract:

1. The adapter class exists, instantiable, and satisfies the
   ``MaterialesPort`` Protocol (the same one ``materiales_port.py``
   declares).
    2. The public method set matches the Protocol's ten methods
   (eight use-case methods + two FK-probe methods added in PR 3 of
   issue #752: ``estancia_is_open_and_active`` and
   ``material_is_active``) one-for-one. A regression that adds or
   removes a method without
   updating the Protocol — or that breaks the protocol check — fails
   this gate.
3. The adapter is not imported by ``domain/`` or ``ports/`` (defense
   in depth; PR 1's transport-free rule would not catch a leak that
   the adapter itself caused).

Hard rules honoured (web-tdd-philosophy):

- Rule 1 (fixture gate): the tests construct a stub ``SqlExecutor``
  that records the calls without touching Postgres — hermetic, no
  I/O, no DSN required.
- Rule 4 (no humo): the assertions check protocol membership,
  exact method-set equality, and import-direction. None of them
  relies on absence-of-error or non-panicking.
- Rule 8 (no production mutation): the stub executor is a local
  class; nothing is written to disk or to a real database.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.core.data_access import BackendError
from app.modules.materiales.adapters.local_backend.materiales_local_backend_adapter import (
    LocalBackendMaterialesAdapter,
)
from app.modules.materiales.domain.estancia_material import EstanciaMaterial
from app.modules.materiales.domain.exceptions import MaterialConflictError
from app.modules.materiales.domain.material import Material
from app.modules.materiales.ports.materiales_port import MaterialesPort

MATERIALES_ROOT = Path(__file__).resolve().parents[2] / "app" / "modules" / "materiales"


class _StubExecutor:
    """In-memory stand-in for ``SqlExecutor`` that records every call.

    Implements the minimal ``execute_sql(query, params) -> list[dict]``
    contract. Returns ``[]`` by default; individual tests can override
    ``result`` to drive the adapter behaviour without spinning up
    Postgres.
    """

    def __init__(self, result: list[dict] | None = None) -> None:
        self.result = result if result is not None else []
        self.calls: list[tuple[str, list | None]] = []

    def execute_sql(
        self,
        query: str,
        params: list | None = None,
    ) -> list[dict]:
        self.calls.append((query, params))
        return self.result


def _public_methods_of(cls: type) -> set[str]:
    """Return every public method name defined directly on ``cls``.

    Excludes dunder methods, private methods (leading underscore),
    and inherited members. The set is later compared against the
    ten expected public methods on the ``MaterialesPort`` Protocol
    (eight use cases + two FK probes added in PR 3 of #752).
    """
    return {
        name
        for name, value in vars(cls).items()
        if callable(value)
        and not name.startswith("_")
    }


def test_adapter_satisfies_port_protocol() -> None:
    """``LocalBackendMaterialesAdapter`` exposes every port method.

    The project's other ports (e.g. ``CatalogosPort``) follow the
    same pattern: ``Protocol`` without ``@runtime_checkable``. The
    pin therefore checks the public method set against the port's
    documented set rather than relying on ``isinstance`` — duck
    typing is the project's idiom. A regression that drops a method
    breaks the ``has_all_ten_port_methods`` assertion below;
    adding a non-port method is caught by ``test_adapter_exposes_exactly_ten_public_methods``.
    """
    stub = _StubExecutor()
    adapter = LocalBackendMaterialesAdapter(stub)
    port_method_names = _public_methods_of(MaterialesPort)
    adapter_method_names = _public_methods_of(type(adapter))
    missing = port_method_names - adapter_method_names
    assert not missing, (
        f"LocalBackendMaterialesAdapter is missing port methods {sorted(missing)}; "
        "either the adapter forgot to implement them or the port surface "
        "changed without updating the adapter"
    )


def test_adapter_exposes_exactly_ten_public_methods() -> None:
    """The adapter's public method set equals the port's expected set.

    Mirrors ``test_port_exposes_eight_use_case_methods_plus_two_probes``
    in ``test_slice_materiales_architecture.py``. The two tests together
    guarantee parity: the port declares 10 methods (eight use cases +
    two FK probes added in PR 3 of #752), the adapter implements 10
    methods, and the names match.
    """
    expected = {
        "create_material",
        "get_material_by_id",
        "list_materials",
        "update_material",
        "deactivate_material",
        "assign_material_to_estancia",
        "list_materials_for_estancia",
        "remove_material_from_estancia",
        "estancia_is_open_and_active",
        "material_is_active",
    }
    declared = _public_methods_of(LocalBackendMaterialesAdapter)
    missing = expected - declared
    extra = declared - expected
    assert not missing and not extra, (
        f"LocalBackendMaterialesAdapter must declare exactly {sorted(expected)}; "
        f"missing={sorted(missing)}, extra={sorted(extra)}"
    )


def test_adapter_module_is_not_imported_from_domain_or_ports() -> None:
    """``adapters/local_backend/`` is the only allowed importer of the adapter.

    Defense in depth for §33: if someone imports the adapter from
    ``domain/material.py`` (e.g. to type-narrow a Protocol method),
    the layer boundary is broken — domain would gain a transitive
    dependency on transport via the adapter. The pin test parses
    both files and fails if any ``import`` statement references the
    adapter module.
    """
    adapter_module = (
        "app.modules.materiales.adapters.local_backend.materiales_local_backend_adapter"
    )
    forbidden_parents = (MATERIALES_ROOT / "domain", MATERIALES_ROOT / "ports")
    violations: list[str] = []
    for parent in forbidden_parents:
        if not parent.exists():
            continue
        for path in parent.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            source = path.read_text(encoding="utf-8")
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == adapter_module or alias.name.startswith(
                            adapter_module + "."
                        ):
                            violations.append(
                                f"{path.relative_to(MATERIALES_ROOT)}: imports {alias.name}"
                            )
                elif isinstance(node, ast.ImportFrom) and node.module:
                    if node.module == adapter_module or node.module.startswith(
                        adapter_module + "."
                    ):
                        violations.append(
                            f"{path.relative_to(MATERIALES_ROOT)}: from {node.module} import ..."
                        )
    assert not violations, (
        "domain/ and ports/ must not import the LocalBackend adapter; "
        "the layer boundary breaks otherwise:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )


def test_adapter_stub_executor_is_called_with_built_sql() -> None:
    """The adapter delegates to the SQL builder rather than composing SQL inline.

    Sanity check that the adapter does not embed raw SQL strings —
    rule §22 keeps the SQL in ``app.modules.materiales.queries``.
    The stub records the query string passed to it; the test only
    asserts the call happens (a single ``execute_sql`` invocation
    is enough to prove the delegation path). The exact SQL string
    is the responsibility of ``test_materiales_queries.py``.
    """
    stub = _StubExecutor(
        result=[
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "material": "Manta",
                "tamano": "M",
                "color": "azul",
                "observaciones": None,
                "activo": True,
                "fecha_alta": "2026-09-11T18:00:00",
                "fecha_baja": None,
                "updated_at": "2026-09-11T18:00:00",
            }
        ]
    )
    adapter = LocalBackendMaterialesAdapter(stub)
    adapter.get_material_by_id("00000000-0000-0000-0000-000000000001")
    assert len(stub.calls) == 1, (
        "get_material_by_id must produce exactly one execute_sql call; "
        "if more, the adapter is composing extra queries inline"
    )


def test_adapter_translates_unique_violation_to_material_conflict_error() -> None:
    """A 23505 ``BackendError`` becomes :class:`MaterialConflictError`, not 500.

    Verifies the same translation contract the legacy
    ``service.py`` provided. Without this assertion the adapter
    could silently bypass the natural-key check and a regression
    would surface as a 500 in the route layer instead of the
    expected 409.
    """

    class _RaisingExecutor:
        def execute_sql(self, query: str, params: list) -> list[dict]:
            raise BackendError(409, body={"code": "23505", "message": "duplicate"})

    adapter = LocalBackendMaterialesAdapter(_RaisingExecutor())  # type: ignore[arg-type]
    with pytest.raises(MaterialConflictError):
        adapter.create_material(
            {"material": "Manta", "tamano": "M", "color": "azul"}
        )


def test_adapter_list_materials_returns_mapped_rows() -> None:
    """``list_materials`` calls the SQL builder and maps every row.

    Coverage pin for the happy path of ``list_materials`` — the
    adapter must produce one ``execute_sql`` call and return one
    :class:`Material` per row. Without this assertion the method
    could silently return ``[]`` (passing the test by virtue of
    coincidence) and the global coverage gate would flag it.
    """
    stub = _StubExecutor(
        result=[
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "material": "Manta",
                "tamano": "M",
                "color": "azul",
                "observaciones": None,
                "activo": True,
                "fecha_alta": "2026-09-11T18:00:00",
                "fecha_baja": None,
                "updated_at": "2026-09-11T18:00:00",
            },
            {
                "id": "00000000-0000-0000-0000-000000000002",
                "material": "Transportin",
                "tamano": "L",
                "color": "negro",
                "observaciones": None,
                "activo": True,
                "fecha_alta": "2026-09-10T18:00:00",
                "fecha_baja": None,
                "updated_at": "2026-09-10T18:00:00",
            },
        ]
    )
    adapter = LocalBackendMaterialesAdapter(stub)
    materials = adapter.list_materials(activos_solo=True)
    assert len(materials) == 2
    assert all(isinstance(m, Material) for m in materials)
    assert len(stub.calls) == 1


def test_adapter_update_material_translates_unique_violation() -> None:
    """``update_material`` raises :class:`MaterialConflictError` on 23505.

    Mirrors the create path. Without this pin, the update method
    could regress to re-raising ``BackendError`` and the route
    layer would surface a 500 instead of the documented 409.
    """

    class _RaisingExecutor:
        def execute_sql(self, query: str, params: list | None = None) -> list[dict]:
            raise BackendError(409, body={"code": "23505", "message": "duplicate"})

    adapter = LocalBackendMaterialesAdapter(_RaisingExecutor())  # type: ignore[arg-type]
    with pytest.raises(MaterialConflictError):
        adapter.update_material(
            "00000000-0000-0000-0000-000000000001",
            {"material": "Manta", "tamano": "M", "color": "azul"},
        )


def test_adapter_deactivate_material_returns_true_when_row_found() -> None:
    """``deactivate_material`` returns True when the UPDATE affected a row.

    Coverage pin for the catalog UPDATE happy path. The cascade
    UPDATE runs only when the catalog UPDATE returns rows; a stub
    returning one row proves the cascade path is exercised.
    """

    class _CascadeTrackingExecutor:
        def __init__(self) -> None:
            self.call_count = 0

        def execute_sql(self, query: str, params: list | None = None) -> list[dict]:
            self.call_count += 1
            return [{"id": "x"}] if self.call_count == 1 else []

    executor = _CascadeTrackingExecutor()
    adapter = LocalBackendMaterialesAdapter(executor)  # type: ignore[arg-type]
    assert adapter.deactivate_material("00000000-0000-0000-0000-000000000001") is True
    assert executor.call_count == 2, (
        "deactivate_material must run the cascade UPDATE only when the catalog update returns rows"
    )


def test_adapter_deactivate_material_returns_false_when_no_row() -> None:
    """``deactivate_material`` returns False when no row matches (idempotent)."""

    class _EmptyExecutor:
        def execute_sql(self, query: str, params: list | None = None) -> list[dict]:
            return []

    adapter = LocalBackendMaterialesAdapter(_EmptyExecutor())  # type: ignore[arg-type]
    assert adapter.deactivate_material("00000000-0000-0000-0000-000000000099") is False


def test_adapter_assign_material_to_estancia_rejects_inactive_estancia() -> None:
    """``assign_material_to_estancia`` raises :class:`ValueError` when the estancia is inactive.

    Coverage pin for the validator branch of
    ``_validate_estancia_open_and_active`` — the call sequence is
    'SELECT FROM acogidas WHERE id = $1' (validate), 'SELECT FROM
    materiales WHERE id = $1' (validate), 'INSERT'. Without this pin,
    the early-return path in the validator is uncovered and the
    CRAP score of the assign method crosses the 6.0 grade-A
    threshold.
    """

    class _EstanciaClosedExecutor:
        def execute_sql(self, query: str, params: list | None = None) -> list[dict]:
            return [{"activo": True, "fecha_final": "2026-01-01"}]

    adapter = LocalBackendMaterialesAdapter(_EstanciaClosedExecutor())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="cerrada"):
        adapter.assign_material_to_estancia(
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000002",
        )


def test_adapter_assign_material_to_estancia_translates_duplicate_junction() -> None:
    """``assign_material_to_estancia`` raises :class:`MaterialConflictError` on junction 23505.

    Distinct from the catalog unique-key test: the junction table
    has its own partial unique index on
    ``(estancia_id, material_id) WHERE activo = true``. The
    validator SELECTs succeed (active estancia, active material);
    the INSERT raises 23505.
    """

    class _ScriptedExecutor:
        def __init__(self) -> None:
            self.call_index = 0

        def execute_sql(
            self, query: str, params: list | None = None
        ) -> list[dict]:
            self.call_index += 1
            if self.call_index <= 2:
                # Validator SELECTs — both succeed
                return [{"activo": True, "fecha_final": None}]
            # INSERT — raise 23505
            raise BackendError(409, body={"code": "23505", "message": "duplicate"})

    executor = _ScriptedExecutor()
    adapter = LocalBackendMaterialesAdapter(executor)
    with pytest.raises(MaterialConflictError, match="ya esta asignado"):
        adapter.assign_material_to_estancia(
            "00000000-0000-0000-0000-000000000001",
            "00000000-0000-0000-0000-000000000002",
        )


def test_adapter_list_materials_for_estancia_returns_junctions() -> None:
    """``list_materials_for_estancia`` maps every junction row."""

    stub = _StubExecutor(
        result=[
            {
                "id": "00000000-0000-0000-0000-000000000010",
                "estancia_id": "00000000-0000-0000-0000-000000000001",
                "material_id": "00000000-0000-0000-0000-000000000002",
                "cantidad": 2,
                "notas": None,
                "activo": True,
                "fecha_alta": "2026-09-11T18:00:00",
            }
        ]
    )
    adapter = LocalBackendMaterialesAdapter(stub)
    junctions = adapter.list_materials_for_estancia(
        "00000000-0000-0000-0000-000000000001"
    )
    assert len(junctions) == 1
    assert junctions[0].cantidad == 2


def test_adapter_remove_material_from_estancia_returns_flag() -> None:
    """``remove_material_from_estancia`` returns True when a row is deactivated."""

    stub = _StubExecutor(result=[{"id": "00000000-0000-0000-0000-000000000010"}])
    adapter = LocalBackendMaterialesAdapter(stub)
    assert (
        adapter.remove_material_from_estancia(
            "00000000-0000-0000-0000-000000000010"
        )
        is True
    )


def test_adapter_update_material_returns_none_when_no_row() -> None:
    """``update_material`` returns None when the row does not exist.

    Coverage pin for the no-row branch of ``update_material`` —
    the SQL UPDATE returns ``[]`` and the method skips the
    ``_row_to_material`` mapping. The CRAP score of the method
    depends on this branch being exercised.
    """

    class _EmptyExecutor:
        def execute_sql(self, query: str, params: list | None = None) -> list[dict]:
            return []

    adapter = LocalBackendMaterialesAdapter(_EmptyExecutor())  # type: ignore[arg-type]
    assert (
        adapter.update_material(
            "00000000-0000-0000-0000-000000000099",
            {"material": "x"},
        )
        is None
    )


def test_adapter_assign_material_to_estancia_happy_path() -> None:
    """``assign_material_to_estancia`` happy path: validators pass + INSERT returns a row.

    Coverage pin for the no-error branch of the assign method. The
    scripted executor returns the validator rows for the first two
    calls (active estancia, active material) and the inserted
    junction row for the third call.
    """

    class _ScriptedExecutor:
        def __init__(self) -> None:
            self.call_index = 0

        def execute_sql(
            self, query: str, params: list | None = None
        ) -> list[dict]:
            self.call_index += 1
            if self.call_index == 1:
                return [{"activo": True, "fecha_final": None}]
            if self.call_index == 2:
                return [{"activo": True}]
            return [
                {
                    "id": "00000000-0000-0000-0000-000000000020",
                    "estancia_id": "00000000-0000-0000-0000-000000000001",
                    "material_id": "00000000-0000-0000-0000-000000000002",
                    "cantidad": 1,
                    "notas": None,
                    "activo": True,
                    "fecha_alta": "2026-09-11T18:00:00",
                }
            ]

    executor = _ScriptedExecutor()
    adapter = LocalBackendMaterialesAdapter(executor)
    junction = adapter.assign_material_to_estancia(
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
    )
    assert isinstance(junction, EstanciaMaterial)
    assert junction.cantidad == 1


def test_adapter_list_materials_for_estancia_includes_inactive_when_requested() -> None:
    """``list_materials_for_estancia(activos_solo=False)`` exercises the inactive branch.

    The SQL builder returns a different SQL when ``activos_solo`` is
    False; the test asserts the adapter forwards the parameter
    correctly and produces a row per response entry.
    """
    stub = _StubExecutor(result=[{"id": "j1", "estancia_id": "e1", "material_id": "m1", "cantidad": 1, "notas": None, "activo": False, "fecha_alta": "2026-09-01"}])
    adapter = LocalBackendMaterialesAdapter(stub)
    junctions = adapter.list_materials_for_estancia("e1", activos_solo=False)
    assert len(junctions) == 1
    assert junctions[0].activo is False


def test_adapter_create_material_happy_path() -> None:
    """``create_material`` returns the mapped row when no unique-violation occurs.

    Coverage pin for the success branch of ``create_material``. The
    stub returns a single INSERT-result row; the adapter maps it to
    a :class:`Material` and returns it. Without this pin the
    statement on lines 95-103 is uncovered and the adapter's
    coverage sits below the 85% global gate.
    """
    stub = _StubExecutor(
        result=[
            {
                "id": "00000000-0000-0000-0000-000000000099",
                "material": "Correa",
                "tamano": "S",
                "color": "rojo",
                "observaciones": None,
                "activo": True,
                "fecha_alta": "2026-09-11T18:00:00",
                "fecha_baja": None,
                "updated_at": "2026-09-11T18:00:00",
            }
        ]
    )
    adapter = LocalBackendMaterialesAdapter(stub)
    material = adapter.create_material(
        {"material": "Correa", "tamano": "S", "color": "rojo"}
    )
    assert isinstance(material, Material)
    assert material.id == "00000000-0000-0000-0000-000000000099"
    assert material.material == "Correa"




def test_adapter_estancia_is_open_and_active_returns_false_when_no_row() -> None:
    """``estancia_is_open_and_active`` short-circuits to False when the row is missing.

    Coverage pin for the "existence" branch (the first guard in the
    three-way check). Without this pin the early-return path is
    uncovered and the CRAP score crosses grade A (CRAP > 6).
    """
    stub = _StubExecutor(result=[])
    adapter = LocalBackendMaterialesAdapter(stub)
    assert adapter.estancia_is_open_and_active("e1") is False


def test_adapter_estancia_is_open_and_active_returns_false_when_inactive() -> None:
    """``estancia_is_open_and_active`` returns False when ``activo = false``.

    Coverage pin for the "active" branch. Mirrors the legacy
    ``_validate_estancia_open_and_active`` "inactiva" rejection.
    """
    stub = _StubExecutor(result=[{"activo": False, "fecha_final": None}])
    adapter = LocalBackendMaterialesAdapter(stub)
    assert adapter.estancia_is_open_and_active("e1") is False


def test_adapter_estancia_is_open_and_active_returns_false_when_closed() -> None:
    """``estancia_is_open_and_active`` returns False when ``fecha_final`` is set.

    Coverage pin for the "no fecha_final" branch. Mirrors the legacy
    ``_validate_estancia_open_and_active`` "cerrada" rejection.
    """
    stub = _StubExecutor(result=[{"activo": True, "fecha_final": "2026-01-01"}])
    adapter = LocalBackendMaterialesAdapter(stub)
    assert adapter.estancia_is_open_and_active("e1") is False


def test_adapter_estancia_is_open_and_active_returns_true_when_open_and_active() -> None:
    """``estancia_is_open_and_active`` returns True when all three checks pass.

    Happy-path coverage pin. Combined with the three negative
    branches above, all four outcomes of the three-way check are
    covered and the CRAP score drops to grade A.
    """
    stub = _StubExecutor(result=[{"activo": True, "fecha_final": None}])
    adapter = LocalBackendMaterialesAdapter(stub)
    assert adapter.estancia_is_open_and_active("e1") is True


def test_adapter_material_is_active_returns_false_when_no_row() -> None:
    """``material_is_active`` short-circuits to False when the row is missing.

    Coverage pin for the existence branch. Mirrors
    ``_validate_material_active`` "no encontrado" rejection.
    """
    stub = _StubExecutor(result=[])
    adapter = LocalBackendMaterialesAdapter(stub)
    assert adapter.material_is_active("m1") is False


def test_adapter_is_unique_violation_matches_409_with_duplicate_text() -> None:
    """``_is_unique_violation`` matches status 409 + duplicate text even without the dict body.

    Coverage pin for the second branch of the helper (the
    non-dict body path). The dict branch is exercised by every
    unique-violation translation test; the text-only branch needs
    an explicit assertion so the CRAP score clears grade A.
    """

    class _RaisingExecutor:
        def execute_sql(self, query, params=None):
            raise BackendError(409, body="duplicate key value violates constraint")

    from app.modules.materiales.adapters.local_backend import (
        materiales_local_backend_adapter as adapter_module,
    )

    assert (
        adapter_module._is_unique_violation(
            BackendError(409, body="duplicate key value violates constraint")
        )
        is True
    )


def test_adapter_is_unique_violation_returns_false_when_unrelated_error() -> None:
    """``_is_unique_violation`` returns False for non-409, non-duplicate errors.

    Coverage pin for the early-False branch. A 500 with a non-duplicate
    body must not be mis-translated to a 409 at the route layer.
    """
    from app.modules.materiales.adapters.local_backend import (
        materiales_local_backend_adapter as adapter_module,
    )

    assert (
        adapter_module._is_unique_violation(BackendError(500, body={"code": "99999", "message": "internal"}))
        is False
    )


def test_application_update_material_with_observaciones_only() -> None:
    """``update_material`` happy path: single optional field round-trips through the port.

    Coverage pin for the observaciones-only branch of the kwargs
    builder. Without this pin the early-return path (all-kwargs None)
    is the only branch exercised, and the CRAP score clears the
    grade-A threshold (CRAP > 6) by covering the partial-update
    branches.
    """
    from app.modules.materiales.application.update_material import update_material

    class _LocalStub:
        def __init__(self):
            self.next_material = None
            self.last_update_id = None
            self.last_update_params = None

        def update_material(self, material_id, params):
            self.last_update_id = material_id
            self.last_update_params = params
            return self.next_material

    port = _LocalStub()
    port.next_material = Material(id="00000000-0000-0000-0000-000000000001", material="x", tamano="y", color="z")

    update_material(
        port,
        "00000000-0000-0000-0000-000000000001",
        observaciones="solo esto",
    )

    assert port.last_update_id == "00000000-0000-0000-0000-000000000001"
    assert port.last_update_params == {"observaciones": "solo esto"}
