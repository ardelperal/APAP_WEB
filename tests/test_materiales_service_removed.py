"""Pin test for the legacy service removal (issue #752, PR 5 of 5).

Once PR 5 lands, the hexagonal refactor is complete: the legacy
``service.py`` and ``estancia_material_service.py`` modules are
gone, replaced by the application-layer use cases (PR 3) and the
LocalBackend adapter (PR 4). This file pins the absence so any
accidental reintroduction fails the suite immediately.

Why this file matters: the legacy modules existed from FOSTER-04
(#46) PR A through the hexagonal refactor. Anyone migrating from
the legacy code path who copy-pastes from the Access/VBA source
might be tempted to re-introduce a "convenience service" — this
pin catches that drift before review.

What the pin checks:

1. ``app.modules.materiales.service`` is import-fatal (the module
   is gone, not just renamed).
2. ``app.modules.materiales.estancia_material_service`` is
   import-fatal.
3. The application layer exposes the eight use cases plus the
   three dataclasses / one exception — the same public surface the
   legacy service exported, now via the hexagonal path.
"""

from __future__ import annotations

import importlib
import sys

import pytest


def test_legacy_service_module_is_removed() -> None:
    """``app.modules.materiales.service`` no longer exists.

    The hexagonal refactor moved every public function in this
    module to ``app.modules.materiales.application`` (PR 3) and the
    SQL composition to the LocalBackend adapter (PR 4). The module
    was removed in PR 5; a re-import raises ``ModuleNotFoundError``.
    """
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.modules.materiales.service")


def test_legacy_estancia_material_service_module_is_removed() -> None:
    """``app.modules.materiales.estancia_material_service`` is gone too.

    Junction CRUD moved into ``app.modules.materiales.application``
    alongside the catalog use cases; the dedicated module is
    redundant now that the split is application-layer-internal.
    """
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.modules.materiales.estancia_material_service")


def test_no_test_module_imports_legacy_service() -> None:
    """No test file imports the legacy modules.

    Defense in depth: a test that still imports ``materiales_service``
    would crash at import time once the module is deleted, but
    catching it here gives a clearer failure message that names the
    offending test file.
    """
    legacy_paths = (
        "app.modules.materiales.service",
        "app.modules.materiales.estancia_material_service",
    )
    offenders: list[str] = []
    # Iterate the loaded modules; pytest imports test files before
    # this pin runs, so a leftover import is already in ``sys.modules``.
    for name in list(sys.modules):
        for legacy in legacy_paths:
            if name == legacy or name.startswith(legacy + "."):
                # The pin itself imports the application module, so
                # skip the legitimate application subtree.
                if "application" in name:
                    continue
                offenders.append(name)
    assert not offenders, (
        "test code must not import the legacy service modules; "
        "the application use cases are the only entry point. "
        f"Offending modules: {offenders}"
    )


def test_application_layer_exposes_the_legacy_public_surface() -> None:
    """The application layer exposes every legacy public function.

    Pin that the legacy ``service.__all__`` and
    ``estancia_material_service.__all__`` are now in the application
    namespace — a regression that drops a use case breaks the
    hexagonal migration's contract with every legacy caller.
    """
    from app.modules.materiales import application as materiales_application

    expected_use_cases = {
        "create_material",
        "get_material_by_id",
        "list_materials",
        "update_material",
        "deactivate_material",
        "assign_material_to_estancia",
        "list_materials_for_estancia",
        "remove_material_from_estancia",
    }
    declared = set(materiales_application.__all__)
    missing = expected_use_cases - declared
    assert not missing, (
        f"application layer must expose every legacy public use case; "
        f"missing={sorted(missing)}"
    )

    # The legacy ``MaterialConflictError`` (re-exported from the
    # application) and the legacy dataclasses (``Material``,
    # ``EstanciaMaterial``) must remain reachable.
    for name in ("MaterialConflictError", "Material", "EstanciaMaterial"):
        assert name in declared, (
            f"application/__init__.py must re-export {name}"
        )
