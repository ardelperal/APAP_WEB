"""Architectural pin test for the auth-dependencies slice (issue #420-7).

This file pins the **new** shape of slice #420-7:

1. The 9 public auth dependencies live in
   :mod:`app.core.di.auth_dependencies_di` (the new composition root).
2. The legacy module :mod:`app.core.auth_dependencies` is a backward-compat
   shim that re-exports the 9 names via ``import *``.
3. The di module does NOT execute raw SQL — it delegates to
   :func:`app.core.auth.get_user_by_email` (the abstracted seam).
4. The §32.P4 ``InsForgeError`` fix in
   :func:`app.core.di.auth_dependencies_di.require_authorized_user` redirects
   to ``/unauthorized`` instead of leaking the transport failure as a 500.

Precedents:

- :mod:`tests.test_catalogos_slice` — the slice-shape pattern (use
  cases delegate to a Port, the adapter holds the SQL, DI provides the
  pooled client).
- :mod:`tests.test_oauth_slice.test_di_layer_does_not_export_domain_or_port`
  — the rule that ``app.core.di`` exposes only FastAPI dependencies, never
  domain entities or ports.

The 7 atoms below cover all four invariants — they fail noisily if any
of them regresses.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from app.core import auth_dependencies as _shim
from app.core.data_access import InsForgeError
from app.core.di import auth_dependencies_di as _di

REPO_ROOT = Path(__file__).resolve().parents[1]
DI_PATH = REPO_ROOT / "app" / "core" / "di" / "auth_dependencies_di.py"
SHIM_PATH = REPO_ROOT / "app" / "core" / "auth_dependencies.py"

NINE_PUBLIC_NAMES = (
    "AuthenticatedUser",
    "is_authenticated_user",
    "get_insforge_client_dep",
    "get_current_user_optional",
    "return_early_if_response",
    "require_authorized_user",
    "require_writer_user",
    "require_developer_user",
    "require_developer_user_redirect",
)


# ---------------------------------------------------------------------------
# Atom 1 — the di module exports exactly the 9 public symbols
# ---------------------------------------------------------------------------


def test_di_module_exports_all_nine_symbols() -> None:
    """``app.core.di.auth_dependencies_di`` exposes the 9 public names.

    The composition root is the canonical home of the slice. The shim
    in :mod:`app.core.auth_dependencies` re-exports the same names.
    A consumer that imports ``app.core.di.auth_dependencies_di`` directly
    MUST see all 9 so the slice is usable without the shim — the
    shim is for backward compatibility, not for exclusivity.
    """
    di_namespace = {n for n in dir(_di) if not n.startswith("_")}
    missing = [n for n in NINE_PUBLIC_NAMES if n not in di_namespace]
    assert not missing, (
        f"app.core.di.auth_dependencies_di must export the 9 public "
        f"auth-dependency symbols; missing: {missing!r}"
    )


# ---------------------------------------------------------------------------
# Atom 2 — the shim re-exports the 9 names with identity (shim.X is di.X)
# ---------------------------------------------------------------------------


def test_shim_reexports_all_nine_symbols() -> None:
    """``app.core.auth_dependencies`` is a thin re-export shim.

    The shim is what the 19 consumer files import. The identity check
    (``shim.X is di.X``) is the contract that lets FastAPI's
    ``app.dependency_overrides[<key>]`` keep working: the override key
    is the function object from the di module, and the shim must hand
    back the SAME object, not a copy or a wrapper.
    """
    shim_namespace = {n for n in dir(_shim) if not n.startswith("_")}
    for name in NINE_PUBLIC_NAMES:
        assert name in shim_namespace, (
            f"app.core.auth_dependencies must re-export {name!r} "
            f"via the shim; missing from dir(shim)"
        )
        shim_attr = getattr(_shim, name)
        di_attr = getattr(_di, name)
        assert shim_attr is di_attr, (
            f"shim.{name} must be the SAME object as di.{name} "
            f"(identity, not just equality); FastAPI's dependency_overrides "
            f"keys on the function object identity"
        )


# ---------------------------------------------------------------------------
# Atom 3 — the di module has no raw SQL and no execute_sql
# ---------------------------------------------------------------------------


def test_di_module_has_no_raw_sql_or_execute_sql() -> None:
    """The di module MUST NOT execute raw SQL — it delegates to a service.

    The composition root holds no transport-shaped imports. The
    revalidation goes through :func:`app.core.auth.get_user_by_email`,
    which is the application-layer seam. If a future change sneaks a
    ``client.execute_sql(...)`` call into the di module, this test
    fails and prevents the leak.

    Note: ``InsForgeClient(...)`` is allowed at the single
    ``get_insforge_client_dep`` call site when ``app.state.insforge_client``
    is absent (lazy fallback for ASGI test transports that skip the
    lifespan). This is the established pattern shared with
    :mod:`app.core.di.oauth_di` and the legacy
    ``app.core.auth_dependencies.get_insforge_client_dep``.
    """
    source = DI_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)

    leaks: list[str] = []
    for node in ast.walk(tree):
        # Detect any call to ``execute_sql`` on any receiver.
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "execute_sql":
                leaks.append(f"raw execute_sql call at line {node.lineno}")
    assert not leaks, (
        f"app.core.di.auth_dependencies_di leaks transport imports "
        f"into the composition root: {leaks!r}"
    )


# ---------------------------------------------------------------------------
# Atom 4 — §32.P4 fix: InsForgeError → 302 + log_safe("auth.denied",
# reason="db_unreachable") + set_cached_auth is NOT called
# ---------------------------------------------------------------------------


class _RaisingInsForgeClient:
    """Spy InsForge client whose ``execute_sql`` raises ``InsForgeError``.

    The application-layer use case (``get_user_by_email``) goes through
    the adapter layer, which calls ``self._executor.execute_sql(...)``
    on the injected client. The spy implements the same interface
    (``execute_sql``) so the full revalidation path is exercised and
    the exception bubbles back to ``require_authorized_user`` as
    ``InsForgeError``.
    """

    def __init__(self, exc: InsForgeError) -> None:
        self._exc = exc
        self.call_count = 0

    def execute_sql(
        self, query: str, params: list[object] | None = None
    ) -> list[dict[str, object]]:
        self.call_count += 1
        raise self._exc


def _fake_request() -> object:
    """A minimal request stub — the dep does not use it on this path."""

    class _State:
        pass

    class _App:
        state = _State()

    class _Request:
        app = _App()

    return _Request()


def test_require_authorized_user_catches_insforge_error_and_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§32.P4 Variant A: ``InsForgeError`` is caught and returns 302.

    Forces :func:`app.core.auth.get_user_by_email` to raise
    ``InsForgeError(503, "service unavailable")`` (the shape the
    PostgREST adapter raises on transport failure). Asserts:

    1. The dep does NOT propagate the exception.
    2. It returns a ``RedirectResponse`` to ``/unauthorized`` (302).
    3. It emits ``log_safe("auth.denied", reason="db_unreachable", ...)``.
    4. It does NOT call ``set_cached_auth`` (would poison the cache
       with a deny verdict based on a transient failure).
    """
    from starlette.responses import RedirectResponse

    captured: list[tuple[str, dict[str, object]]] = []

    def _capture(event: str, **fields: object) -> None:
        captured.append((event, fields))

    # Capture log_safe from the shim (the di module reads log_safe
    # through the shim at call time, so patching the shim's log_safe
    # is what the existing tests do — mirrors the fail-closed contract
    # of the rest of the auth dep test suite).
    monkeypatch.setattr(_shim, "log_safe", _capture)

    # Capture set_cached_auth calls — the fix MUST NOT poison the cache.
    set_calls: list[dict[str, object]] = []

    def _fake_set_cached_auth(
        email: str, *, is_authorized: bool, rol: str | None
    ) -> None:
        set_calls.append(
            {"email": email, "is_authorized": is_authorized, "rol": rol}
        )

    monkeypatch.setattr(_di, "set_cached_auth", _fake_set_cached_auth)

    # The dep reads the TTL from settings; default 300s is fine.
    # Clear the auth cache so the test starts from a guaranteed miss.
    from app.core import auth_cache as _auth_cache
    _auth_cache.invalidate_all()

    result = _di.require_authorized_user(
        request=_fake_request(),
        payload={
            "email": "u@example.com",
            "user_id": "u-1",
            "rol": "key_user",
            "is_authorized": True,
        },
        client=_RaisingInsForgeClient(InsForgeError(503, "service unavailable")),
    )

    # Assertion 1: a RedirectResponse is returned — no exception escaped.
    assert isinstance(result, RedirectResponse), (
        f"§32.P4 fix: require_authorized_user MUST return a RedirectResponse "
        f"on InsForgeError, not raise. Got: {result!r}"
    )
    # Assertion 2: 302 to /unauthorized.
    assert result.status_code == 302
    assert result.headers["location"] == "/unauthorized"

    # Assertion 3: log_safe was called with the right event + reason.
    denial_events = [
        (event, fields)
        for event, fields in captured
        if event == "auth.denied" and fields.get("reason") == "db_unreachable"
    ]
    assert denial_events, (
        f"§32.P4 fix: require_authorized_user MUST emit auth.denied with "
        f"reason=db_unreachable on InsForgeError; got: {captured!r}"
    )
    # user_id is propagated from the payload (no PII leak).
    assert denial_events[0][1].get("user_id") == "u-1"
    assert "email" not in denial_events[0][1]

    # Assertion 4: set_cached_auth was NOT called (cache-poisoning guard).
    assert set_calls == [], (
        f"§32.P4 fix: a transient DB outage MUST NOT poison the auth cache "
        f"with a deny verdict. set_cached_auth calls observed: {set_calls!r}"
    )


# ---------------------------------------------------------------------------
# Atom 5 — the 9 signatures match between shim and di module
# ---------------------------------------------------------------------------


def test_di_module_nine_signatures_match_shim_byte_for_byte() -> None:
    """Each callable symbol has the same signature in the shim and the di module.

    This is the byte-identical-signature contract (R09) for the 8
    callable symbols. FastAPI's ``app.dependency_overrides[<key>]``
    keys on the function object identity (covered by atom 2); the test
    files additionally key on the signature to type-check
    ``Depends(...)`` resolution. If a return type or default changes
    between the shim and the di module, this test fails.

    The 9th symbol, ``AuthenticatedUser`` (a TypedDict class), has no
    ``inspect.signature`` and is excluded — atom 2 already pins its
    identity (``shim.AuthenticatedUser is di.AuthenticatedUser``).
    """
    callable_names = tuple(n for n in NINE_PUBLIC_NAMES if n != "AuthenticatedUser")
    for name in callable_names:
        shim_obj = getattr(_shim, name)
        di_obj = getattr(_di, name)
        assert callable(shim_obj), (
            f"shim.{name} must be a callable (FastAPI dependency)"
        )
        shim_sig = inspect.signature(shim_obj)
        di_sig = inspect.signature(di_obj)
        assert shim_sig == di_sig, (
            f"signature drift on {name!r}: shim={shim_sig!r} di={di_sig!r}"
        )


# ---------------------------------------------------------------------------
# Atom 6 — the di module is under the 700-line module-size budget
# ---------------------------------------------------------------------------


def test_di_module_under_module_size_budget() -> None:
    """The di module MUST stay under the 700-line module-size budget (rule §21).

    The 700-line cap is enforced by ``scripts/check_module_size.py`` in
    CI. This atom keeps the same number pinned in a focused unit test
    so a regression here surfaces immediately, not behind the ratchet.
    """
    line_count = sum(1 for _ in DI_PATH.read_text(encoding="utf-8").splitlines())
    assert line_count <= 700, (
        f"app.core.di.auth_dependencies_di.py is {line_count} lines; "
        f"the module-size budget (rule §21) is 700 lines. Split the file "
        f"if it grows past the cap."
    )


# ---------------------------------------------------------------------------
# Atom 7 — the shim is under the 50-line cap
# ---------------------------------------------------------------------------


def test_shim_under_fifty_lines() -> None:
    """The shim MUST stay under 50 lines (the slice's hard cap).

    The shim is a re-export. A shim that grows past 50 lines is hiding
    real logic. Atom 7 catches drift the moment it appears.
    """
    line_count = sum(1 for _ in SHIM_PATH.read_text(encoding="utf-8").splitlines())
    assert line_count <= 50, (
        f"app.core.auth_dependencies.py is {line_count} lines; the shim "
        f"cap is 50 lines. If it grew past 50, the shim is hiding logic "
        f"that belongs in app.core.di.auth_dependencies_di."
    )
