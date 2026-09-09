"""Architectural pin tests for the ``insforge_error_handler`` slice.

Issue #420 (slice migration): the legacy 58-line
``app/core/insforge_error_handler.py`` was replaced by a hexagonal
slice. These tests pin two architectural invariants that make the
slice regression-proof:

1. The :mod:`app.core.ports.insforge_error_handler_port` module is
   100% transport-free — no import from
   :mod:`app.core.insforge` (the transport client) nor from
   :mod:`app.core.data_access` (the transport-shaped exception
   class). The Protocol boundary is what keeps rule §31 (domain
   depends on Protocol abstractions) honest.
2. The application layer (:mod:`app.core.application.insforge_error_handler`)
   does NOT import :class:`InsForgeError` directly. The application
   reads the target exception class from the port.
3. The DI module (:mod:`app.core.di.insforge_error_handler_di`)
   does NOT import the application layer's
   :func:`register_insforge_error_handler` — it owns the port
   factory only.
4. The legacy shim :mod:`app.core.insforge_error_handler` is a
   5-line backward-compat re-export; its body never declares the
   function, only imports it.

Each pin is a regex over the file body. The tests run in isolation
(no transport, no InsForge, no HTTP) so they belong in the
default test run, not behind an env-var gate (the §32.P6 family
of "tests that exist but never run" anti-pattern).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    """Return the verbatim contents of ``rel_path`` relative to the repo root."""
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


def test_port_module_is_transport_free() -> None:
    """The port module imports neither ``app.core.insforge`` nor ``app.core.data_access``.

    Rule §31: domain services (and the ports they depend on) must
    import Protocol abstractions, never concrete transport
    surfaces. ``app.core.insforge`` is the transport client
    (SqlExecutor + REST wrappers); ``app.core.data_access``
    declares the transport-shaped exception hierarchy (DataAccessError
    / InsForgeError / DuplicateKeyError). The adapter owns both;
    the port stays abstract.
    """
    body = _read("app/core/ports/insforge_error_handler_port.py")

    forbidden_imports = (
        re.compile(r"^\s*from\s+app\.core\.insforge(\.|\s)", re.MULTILINE),
        re.compile(r"^\s*from\s+app\.core\.insforge\s+import\s+", re.MULTILINE),
        re.compile(
            r"^\s*from\s+app\.core\.data_access(\.|\s)", re.MULTILINE
        ),
        re.compile(
            r"^\s*from\s+app\.core\.data_access\s+import\s+", re.MULTILINE
        ),
    )

    violations = [
        pattern.pattern
        for pattern in forbidden_imports
        if pattern.search(body)
    ]
    assert not violations, (
        "insforge_error_handler_port.py must stay transport-free; "
        f"found forbidden import(s): {violations}"
    )


def test_shim_is_not_a_pure_reexport() -> None:
    """The shim OWNS the registration logic; it is NOT a re-export.

    The slice intentionally has no ``application/`` layer (the
    use case is a trivial one-line ``port.to_user_response(exc)``
    call). The shim imports ports + logging + FastAPI and registers
    the handler directly. The ``register_insforge_error_handler``
    symbol must be DEFINED here, not imported from another module.

    This is a §33 deviation from the established slice pattern
    (oauth / auth / admin all have an application layer). The
    deviation is recorded in the shim's module docstring.

    Phase 3 (issue #641): the shim was renamed from
    ``app/core/insforge_error_handler.py`` to ``app/core/error_handler.py``
    when the InsForge transport was retired. The test now reads the
    renamed location.
    """
    body = _read("app/core/error_handler.py")

    assert "def register_insforge_error_handler" in body, (
        "shim must DEFINE register_insforge_error_handler; the slice "
        "has no application layer (the use case is trivial)."
    )
    # No `from app.core.application.insforge_error_handler import`
    # because that package does not exist.
    forbidden = re.compile(
        r"^\s*from\s+app\.core\.application\.insforge_error_handler\s+import",
        re.MULTILINE,
    )
    assert not forbidden.search(body), (
        "shim must not import from a non-existent application layer."
    )


def test_di_module_does_not_import_shim() -> None:
    """The DI module wires ports; it does NOT import the shim's registration function.

    The DI owns the per-transport adapter instances; the shim owns
    the FastAPI registration. The two layers communicate through
    the port, not through each other. ``app/main.py`` (delivery)
    is the only caller that wires them together.
    """
    body = _read("app/core/di/insforge_error_handler_di.py")

    forbidden = re.compile(
        r"^\s*from\s+app\.core\.insforge_error_handler\s+import",
        re.MULTILINE,
    )
    assert not forbidden.search(body), (
        "di/insforge_error_handler_di.py must not import the shim; "
        "that is the caller's job (app/main.py)."
    )


def test_adapter_is_the_only_importer_of_insforge_error() -> None:
    """Only the InsForge adapter imports ``InsForgeError``.

    The adapter is the seam where the transport-shaped exception
    class meets the abstract port. Anywhere else in the slice
    that imports ``InsForgeError`` would mean transport leaked
    into the wrong layer. Docstring mentions of the class name
    (e.g. ``# this used to import InsForgeError``) are fine — the
    pin only fires on real ``import`` statements.

    Phase 3 (issue #641): the per-transport adapter
    (``app/core/adapters/insforge/insforge_error_handler_insforge_adapter.py``)
    was deleted; ``BackendErrorTranslation`` (the adapter) now lives in
    ``app/core/di/insforge_error_handler_di.py``. The ``insforge_error_handler.py``
    shim was renamed to ``error_handler.py``. The pin walks the new
    locations and asserts none of them import ``InsForgeError``
    (the exception class is now in :mod:`app.core.data_access` and is
    named ``BackendError``; ``InsForgeError`` survives as a backward-
    compat alias that the production code never imports by name).
    """
    # Match `from X import ...InsForgeError...` and `import X.InsForgeError`
    # as standalone top-level statements (not inside docstrings or comments).
    import_pattern = re.compile(
        r"^\s*(?:from\s+[\w.]+\s+import\s+.*\bInsForgeError\b"
        r"|import\s+[\w.]*InsForgeError\b)",
        re.MULTILINE,
    )
    files_with_import: list[str] = []
    for rel in (
        "app/core/ports/insforge_error_handler_port.py",
        "app/core/di/insforge_error_handler_di.py",
        "app/core/error_handler.py",
    ):
        body = _read(rel)
        if import_pattern.search(body):
            files_with_import.append(rel)

    assert files_with_import == [], (
        "None of the error-handler slice modules may import "
        "InsForgeError by name; the class lives in app.core.data_access "
        "as BackendError and the adapter (di/insforge_error_handler_di.py) "
        "binds it via Protocol, not by direct import. "
        f"Found import statement(s) in: {files_with_import}"
    )


def test_legacy_shim_has_no_transport_import() -> None:
    """The shim itself stays transport-free — only the application module imports below it.

    The shim is a re-export; it must not re-introduce the
    ``from app.core.insforge import InsForgeError`` coupling the
    legacy module had.

    Phase 3 (issue #641): the shim was renamed from
    ``app/core/insforge_error_handler.py`` to ``app/core/error_handler.py``.
    The pin reads the renamed location.
    """
    body = _read("app/core/error_handler.py")
    forbidden = (
        re.compile(r"from\s+app\.core\.insforge(\.|\s)", re.MULTILINE),
        re.compile(
            r"from\s+app\.core\.data_access(\.|\s)", re.MULTILINE
        ),
    )
    violations = [p.pattern for p in forbidden if p.search(body)]
    assert not violations, (
        "shim must stay transport-free; found forbidden import(s): "
        f"{violations}"
    )


def test_ports_package_reexports_new_port() -> None:
    """``app/core/ports/__init__.py`` re-exports the new port alongside the existing ones."""
    body = _read("app/core/ports/__init__.py")
    assert "ErrorTranslationPort" in body, (
        "app/core/ports/__init__.py must re-export ErrorTranslationPort "
        "so the application's `from app.core.ports import ...` style works."
    )
    assert "TranslatableError" in body, (
        "app/core/ports/__init__.py must re-export TranslatableError "
        "alongside ErrorTranslationPort."
    )
    assert "ErrorUserResponse" in body


def test_insforge_adapter_package_reexports_new_adapter() -> None:
    """``app/core/adapters/insforge/__init__.py`` re-exports the new adapter."""
    body = _read("app/core/adapters/insforge/__init__.py")
    assert "InsForgeErrorTranslation" in body, (
        "app/core/adapters/insforge/__init__.py must re-export "
        "InsForgeErrorTranslation alongside the other InsForge adapters."
    )


__all__ = [
    "test_adapter_is_the_only_importer_of_insforge_error",
    "test_di_module_does_not_import_shim",
    "test_insforge_adapter_package_reexports_new_adapter",
    "test_legacy_shim_has_no_transport_import",
    "test_port_module_is_transport_free",
    "test_ports_package_reexports_new_port",
    "test_shim_is_not_a_pure_reexport",
]
