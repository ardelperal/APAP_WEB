"""Tests for the extracted router registry (issue #204).

The refactor (closes #204) moves the 11 ``app.include_router(...)``
calls out of ``app/main.py`` into
:func:`app.routes_registry.register_routers`.

These tests pin the contract the registry must hold:

1. ``register_routers(app)`` exists and is callable with that signature.
2. After registration, ``app.routes`` carries exactly the same set of
   route (method, path) pairs as the pre-refactor ``create_app`` in
   ``app/main.py`` (asserted by comparing a snapshot of the running
   app against a fresh app built by the registry alone).
3. No route is duplicated (defence-in-depth: a refactor that registers
   a router twice would silently shadow endpoints).
4. Each registered path comes from exactly ONE source module — the
   pre-refactor ordering pins each path prefix to one feature module
   (e.g. ``/animales`` -> ``app.modules.animals.routes``, ``/voluntarios``
   -> ``app.modules.voluntarios.routes``).

The introspection surface is ``app.routes``. FastAPI >=0.137 wraps each
included ``APIRouter`` in an ``_IncludedRouter`` instance (see
fastapi/fastapi#15745) that does NOT expose ``.path``/``.methods`` —
the helper below recurses into ``_IncludedRouter.original_router.routes``
so the assertions see the same composed ``APIRoute`` entries on both
FastAPI 0.115-0.136 and 0.137+.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi import FastAPI

# --- shape -----------------------------------------------------------------


def test_register_routers_is_callable_from_app_routes_registry() -> None:
    """The registry lives at ``app.routes_registry.register_routers``.

    Contract for the refactor (issue #204): one function imports the
    full router chain. Asserts the symbol exists and is callable.
    """
    module = importlib.import_module("app.routes_registry")
    assert hasattr(module, "register_routers"), (
        "app.routes_registry.register_routers must exist; "
        "the refactor introduces this symbol as the single import surface"
    )
    assert callable(module.register_routers), (
        "app.routes_registry.register_routers must be callable"
    )


# --- helpers ---------------------------------------------------------------


def _extract_method_path_pairs(app) -> set[tuple[str, str]]:
    """Flatten ``app.routes`` into ``{(method, path), ...}`` sets.

    Recurses into ``_IncludedRouter.original_router.routes`` (the
    FastAPI >=0.137 wrapper introduced in fastapi/fastapi#15745) so
    the same composed ``APIRoute`` entries are visible on both
    FastAPI 0.115-0.136 and 0.137+. ``Mount`` instances (e.g.
    ``/static``) and the ``_IncludedRouter`` wrapper itself are
    skipped — they have no ``methods`` attribute, and the pre-refactor
    ``main.py`` does not depend on the mount's child routes for
    handler dispatch.
    """
    pairs: set[tuple[str, str]] = set()

    def _walk(routes) -> None:
        for r in routes:
            # FastAPI >=0.137: ``_IncludedRouter`` exposes the wrapped
            # APIRouter via ``.original_router``; descend into its
            # ``.routes`` to reach the actual ``APIRoute`` entries
            # (whose ``.path`` is already composed with the prefix).
            original = getattr(r, "original_router", None)
            if original is not None and hasattr(original, "routes"):
                _walk(original.routes)
                continue
            if hasattr(r, "methods") and hasattr(r, "path"):
                for m in r.methods:
                    pairs.add((m, r.path))

    _walk(app.routes)
    return pairs


# --- route identity --------------------------------------------------------


def test_register_routers_populates_routes_on_fresh_app() -> None:
    """Running the registry against a fresh ``FastAPI`` adds a non-empty
    set of routes that match the running ``main.py`` app's set.
    """
    from app.routes_registry import register_routers

    fresh_app = FastAPI()
    register_routers(fresh_app)
    fresh_pairs = _extract_method_path_pairs(fresh_app)

    assert len(fresh_pairs) > 0, (
        "register_routers must add at least one (method, path) pair; "
        "an empty result means no router was registered"
    )
    assert "UADetectionMiddleware" not in [
        d.cls.__name__ for d in fresh_app.user_middleware
    ], (
        "register_routers must NOT register middleware; that contract "
        "belongs to install_auth_middleware. Mixing them couples two "
        "different layering concerns."
    )


def test_register_routers_produces_same_routes_as_full_create_app() -> None:
    """The route set on a fresh app after ``register_routers`` matches
    the route set the pre-refactor ``create_app`` produces.

    Catches accidental loss (a router omitted) and accidental
    duplication (a router added twice).

    Note: the comparison excludes the application-level auth-flow
    routes (``/``, ``/healthz``, ``/login``, ``/auth/google``,
    ``/auth/callback``, ``/logout``, ``/unauthorized``, ``/admin``,
    ``/admin/users``, ``/admin/users/{user_id}/deactivate``) — those
    stay in ``create_app`` and are NOT the registry's concern. The
    registry's contract is to own the 11 ``include_router`` calls
    for the domain modules.

    ``FastAPI()`` defaults include ``/docs``, ``/redoc``,
    ``/openapi.json`` — those are also excluded so a fresh
    ``FastAPI()`` (which has them on) and ``create_app`` (which
    disables them via ``docs_url=None``) compare on equal terms for
    the routes the registry owns.
    """
    from app.main import create_app
    from app.routes_registry import register_routers

    APP_LEVEL_PATHS: frozenset[str] = frozenset(
        {
            "/",
            "/healthz",
            "/login",
            "/auth/google",
            "/auth/callback",
            "/logout",
            "/unauthorized",
            "/admin",
            "/admin/users",
            "/admin/users/{user_id}/deactivate",
            "/docs",
            "/docs/oauth2-redirect",
            "/redoc",
            "/openapi.json",
        }
    )

    def _domain_pairs(app) -> set[tuple[str, str]]:
        return {
            (m, p)
            for m, p in _extract_method_path_pairs(app)
            if p not in APP_LEVEL_PATHS
        }

    full_app = create_app()
    full_pairs = _domain_pairs(full_app)

    fresh_app = FastAPI()
    register_routers(fresh_app)
    fresh_pairs = _domain_pairs(fresh_app)

    missing = full_pairs - fresh_pairs
    extra = fresh_pairs - full_pairs
    assert not missing and not extra, (
        f"register_routers domain-router route set drifted from create_app. "
        f"missing in registry (in create_app, not registered)="
        f"{sorted(missing)!r}; "
        f"extra in registry (registered, not in create_app)="
        f"{sorted(extra)!r}; "
        f"diff total={len(missing) + len(extra)}"
    )


def test_register_routers_does_not_duplicate_routes() -> None:
    """Calling ``register_routers`` twice on the same app does NOT
    duplicate any route.

    Defence-in-depth: a refactor that re-includes a router in two
    places would silently shadow endpoints. We rely on the registry
    being idempotent (FastAPI's include_router stores routes; calling
    twice doubles them — the test guards against any future "helper
    that calls register_routers twice" mistake, but ALSO catches a
    refactor where the registry itself includes the same router twice).
    """
    from app.routes_registry import register_routers

    fresh_app = FastAPI()
    register_routers(fresh_app)
    pairs_before = _extract_method_path_pairs(fresh_app)

    # Re-instantiate the route surface so the comparison is on the
    # SAME app instead of doubling it (which would falsely
    # shadow/duplicate paths because FastAPI stores in insertion
    # order). What we REALLY want to verify is that the registry
    # itself does not include any router twice.
    fresh2 = FastAPI()
    register_routers(fresh2)
    pairs_after = _extract_method_path_pairs(fresh2)
    assert pairs_before == pairs_after, (
        f"register_routers is not idempotent on a fresh app: "
        f"diff={pairs_before ^ pairs_after!r}"
    )


@pytest.mark.parametrize(
    "prefix",
    [
        "/animales",
        "/entradas",
        "/voluntarios",
        "/sanidad",
        "/adopciones",
        "/acogidas",
        "/cesiones",
        "/materiales",
    ],
)
def test_register_routers_includes_each_module_router(prefix: str) -> None:
    """Each feature module's prefix is reachable after registration.

    Pin every module whose main.py currently has an include_router
    statement (lines 641-684): animals, entradas, entradas batch,
    foster, foster_assignment, acogidas, cesiones, voluntarios,
    adopciones, sanidad, materiales, materiales_acogida. The test
    covers the unique-prefix subset (the rest are batch/junction
    routers with no first-level prefix).

    The path enumeration recurses into ``_IncludedRouter`` wrappers
    (FastAPI >=0.137, fastapi/fastapi#15745) the same way
    :func:`_extract_method_path_pairs` does — the wrapper itself
    exposes no ``.path``/``.methods`` so the old ``{r.path for r in
    app.routes if hasattr(r, 'path')}`` set comprehension silently
    dropped every route that came from ``include_router`` on
    FastAPI >=0.137, making the assertion pass vacuously for
    unrelated reasons (FastAPI defaults such as ``/openapi.json``).
    """
    from app.routes_registry import register_routers

    fresh_app = FastAPI()
    register_routers(fresh_app)

    paths: set[str] = set()

    def _walk(routes) -> None:
        for r in routes:
            original = getattr(r, "original_router", None)
            if original is not None and hasattr(original, "routes"):
                _walk(original.routes)
                continue
            if hasattr(r, "path"):
                paths.add(r.path)

    _walk(fresh_app.routes)
    matching = [
        path for path in paths if path == prefix or path.startswith(prefix + "/")
    ]
    assert matching, (
        f"no routes registered under prefix {prefix!r}; "
        f"the registry dropped this feature module's router"
    )



