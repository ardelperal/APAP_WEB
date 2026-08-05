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
import re
import subprocess
import sys
import textwrap
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
# Atom 3 — the di module has no raw SQL, no direct insforge imports, and no
# transport-shaped construction (R04 leak constraint, full set)
# ---------------------------------------------------------------------------


# R04 — the leak constraint, in machine-checkable form. Any of these in
# the di module body would mean the composition root bypasses the
# service seam and reaches the transport directly.
_RAW_SQL_KEYWORDS = (
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "CREATE",
    "DROP",
    "ALTER",
)


def _module_r04_violations(source: str) -> list[str]:
    """Walk the AST and return a list of R04 violation descriptions.

    A violation is any of:

    1. A raw SQL keyword (``SELECT``, ``INSERT``, ``UPDATE``, ``DELETE``,
       ``CREATE``, ``DROP``, ``ALTER``) appearing as a string-literal
       inside the module body — but NOT inside docstrings (the module
       docstring describes ``POST/PUT/PATCH/DELETE`` HTTP methods, not
       raw SQL keywords).
    2. An ``InsForgeClient(...)`` constructor call OUTSIDE the single
       permitted fallback site inside ``get_insforge_client_dep``.
       Importing ``InsForgeClient`` at module level IS allowed — it is
       the only construction site permitted, and the fallback needs
       the symbol in scope.
    3. A direct attribute access of ``auth_cache`` (the module must go
       through the ``get_cached_auth`` / ``set_cached_auth`` facade,
       not reach into the cache module directly).

    Returns:
        A list of human-readable violation descriptions. Empty list =
        no leaks.
    """
    violations: list[str] = []
    tree = ast.parse(source)

    def _enclosing_function(node: ast.AST) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        current = node
        while hasattr(current, "parent"):
            current = current.parent  # type: ignore[attr-defined]
            if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return current
        return None

    # ast.walk() doesn't surface parents — build a parent map.
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            child.parent = parent  # type: ignore[attr-defined]

    def _is_docstring(node: ast.Constant) -> bool:
        """Return True if ``node`` is a docstring (skip it for SQL scan).

        A docstring in Python's AST is the FIRST statement of a
        Module/FunctionDef/AsyncFunctionDef/ClassDef body, and it is
        the value of an ``ast.Expr`` wrapping a string Constant.
        """
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            return False
        parent = getattr(node, "parent", None)
        if not isinstance(parent, ast.Expr):
            return False
        grandparent = getattr(parent, "parent", None)
        body = getattr(grandparent, "body", None)
        if body is None or len(body) == 0:
            return False
        return body[0] is parent

    # ---- Constraint 1: raw SQL keywords in string literals (skip docstrings).
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if _is_docstring(node):
            # Docstrings may mention HTTP methods (POST/PUT/PATCH/DELETE)
            # or describe public APIs in English/Spanish — that is
            # documentation, not code. Raw SQL appears only in code
            # strings (``client.execute_sql("SELECT ...")``).
            continue
        text = node.value.upper()
        for kw in _RAW_SQL_KEYWORDS:
            pattern = rf"\b{kw}\b"
            if re.search(pattern, text):
                violations.append(
                    f"raw SQL keyword {kw!r} in code string literal at line {node.lineno}"
                )
                break

    # ---- Constraint 2: ``InsForgeClient(...)`` constructor outside the
    # permitted fallback site.
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Name) and func.id == "InsForgeClient"):
            continue
        enclosing = _enclosing_function(node)
        if enclosing is None or enclosing.name != "get_insforge_client_dep":
            violations.append(
                f"InsForgeClient(...) construction at line {node.lineno} "
                f"outside the permitted get_insforge_client_dep fallback "
                f"site (the service seam must own this)"
            )

    # ---- Constraint 3: direct attribute access of ``auth_cache`` or
    # unauthorized import from the auth_cache module. The composition
    # root only touches the cache through the module-level facade
    # (``get_cached_auth`` / ``set_cached_auth`` imported at the top).
    # Reaching for ``app.core.auth_cache.<name>`` directly would
    # bypass the in-process backend abstraction (issue #287).
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            value = node.value
            if isinstance(value, ast.Name) and value.id == "auth_cache":
                violations.append(
                    f"direct access to app.core.auth_cache.{node.attr} at "
                    f"line {node.lineno} (must use the get_cached_auth / "
                    f"set_cached_auth facade)"
                )
        if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith(
            "auth_cache"
        ):
            if any(name not in {"get_cached_auth", "set_cached_auth"} for name in (
                alias.name for alias in node.names
            )):
                violations.append(
                    f"unauthorized import from app.core.auth_cache at "
                    f"line {node.lineno} (only get_cached_auth / "
                    f"set_cached_auth are permitted)"
                )

    return violations


def test_di_module_has_no_raw_sql_or_execute_sql() -> None:
    """The di module MUST NOT execute raw SQL, import transport, or
    bypass the service seam — full R04 leak constraint set.

    The composition root holds no transport-shaped imports. The
    revalidation goes through :func:`app.core.auth.get_user_by_email`,
    which is the application-layer seam. If a future change sneaks a
    ``client.execute_sql(...)`` call into the di module, this test
    fails and prevents the leak.

    The three checks enforced here are the complete R04 set:

    1. **No raw SQL** — no ``SELECT`` / ``INSERT`` / ``UPDATE`` / ``DELETE``
       / ``CREATE`` / ``DROP`` / ``ALTER`` string literal in the module
       code (docstrings excluded — they may mention HTTP methods like
       ``POST/PUT/PATCH/DELETE`` in plain English/Spanish).
    2. **No transport construction outside the permitted fallback** —
       ``InsForgeClient(...)`` is allowed ONLY inside
       ``get_insforge_client_dep`` at the lazy fallback site (a single
       line, when ``app.state.insforge_client`` is absent). Importing
       ``InsForgeClient`` at module level is permitted because that
       single function needs the symbol in scope.
    3. **No direct ``app.core.auth_cache`` access** — the di module must
       use the ``get_cached_auth`` / ``set_cached_auth`` facade and must
       not import other symbols from the cache module.

    Note: importing ``get_cached_auth`` and ``set_cached_auth`` FROM
    ``app.core.auth_cache`` at module level IS allowed (constraint 3's
    exception clause) — that is the facade wiring.
    """
    source = DI_PATH.read_text(encoding="utf-8")
    violations = _module_r04_violations(source)
    assert not violations, (
        f"app.core.di.auth_dependencies_di violates the R04 leak "
        f"constraint — the composition root must not bypass the service "
        f"seam. Violations: {violations!r}"
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


class _SetCachedAuthSpy:
    """Spy on :func:`app.core.auth_cache.set_cached_auth`.

    Records every call into ``self.calls`` and exposes the count via
    ``self.call_count``. The §32.P4 fix MUST NOT call ``set_cached_auth``
    on a transient DB outage — pinning ``call_count == 0`` catches the
    regression if a future change removes the negative guard.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.call_count: int = 0

    def __call__(
        self, email: str, *, is_authorized: bool, rol: str | None
    ) -> None:
        self.call_count += 1
        self.calls.append(
            {"email": email, "is_authorized": is_authorized, "rol": rol}
        )


@pytest.fixture
def set_cached_auth(monkeypatch: pytest.MonkeyPatch) -> _SetCachedAuthSpy:
    """Install a :class:`_SetCachedAuthSpy` and clear the cache.

    The spy is wired into both the source module
    (``app.core.auth_cache.set_cached_auth``) and the di module's
    local rebinding (``_di.set_cached_auth``) so the production call
    site is observed regardless of which alias was used at import time.
    Yields the spy so the test can read ``spy.call_count``.
    """
    from app.core import auth_cache as _auth_cache

    spy = _SetCachedAuthSpy()
    monkeypatch.setattr(
        "app.core.auth_cache.set_cached_auth", spy
    )
    monkeypatch.setattr(_di, "set_cached_auth", spy)
    _auth_cache.invalidate_all()
    yield spy
    _auth_cache.invalidate_all()


def test_require_authorized_user_catches_insforge_error_and_redirects(
    monkeypatch: pytest.MonkeyPatch,
    set_cached_auth,
) -> None:
    """§32.P4 Variant A: ``InsForgeError`` is caught and returns 302.

    Forces :func:`app.core.auth.get_user_by_email` to raise
    ``InsForgeError(503, "service unavailable")`` (the shape the
    PostgREST adapter raises on transport failure). Asserts:

    1. The dep does NOT propagate the exception.
    2. It returns a ``RedirectResponse`` to ``/unauthorized`` (302).
    3. It emits ``log_safe("auth.denied", reason="db_unreachable", ...)``.
    4. It does NOT call ``set_cached_auth`` (would poison the cache
       with a deny verdict based on a transient failure) — pinned
       with the ``set_cached_auth`` fixture's ``spy.call_count``.
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
    # The ``set_cached_auth`` fixture installs a spy on both the source
    # module (``app.core.auth_cache.set_cached_auth``) and the di
    # module's local rebinding; the production dep call site must
    # never invoke it on a transient DB outage. Pinned via
    # ``spy.call_count``, not the empty-list trick (which would not
    # detect the bug if the spy was incorrectly never wired in).
    assert set_cached_auth.call_count == 0, (
        f"§32.P4 fix: a transient DB outage MUST NOT poison the auth cache "
        f"with a deny verdict. set_cached_auth calls observed: "
        f"{set_cached_auth.calls!r}"
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


# ---------------------------------------------------------------------------
# Atom 8 — fresh-process regression test for the di↔shim module-level cycle
# ---------------------------------------------------------------------------


def test_shim_exports_resolve_when_di_module_imported_first() -> None:
    """The shim MUST re-export the 9 public names when the di module
    is imported FIRST in a fresh Python process.

    Regression test for the module-level cycle. A fresh process that
    imports ``app.core.di.auth_dependencies_di`` BEFORE
    ``app.core.auth_dependencies`` used to silently break the shim's
    re-exports:

      1. The di module's module-level
         ``from app.core import auth_dependencies as _shim`` triggered
         shim load.
      2. The shim's first line,
         ``from app.core.di.auth_dependencies_di import *``, ran
         against the PARTIAL di module (the 9 public symbols are
         defined AFTER the di module's shim-import line, so at that
         moment only stdlib imports are bound).
      3. The star-import re-exported nothing.
      4. The shim finished with ``log_safe`` and
         ``read_session_payload`` but no consumer-facing 9 names.
      5. Any consumer
         (``from app.core.auth_dependencies import require_authorized_user``)
         then raised ``ImportError``.

    With the cycle fix (defer the shim lookup to call time via
    ``_shim()``), the di module's load does not touch the shim.
    Whichever order a fresh process loads the two modules, the shim
    ends up with all 9 public names and identity preserved
    (``shim.<name> is di.<name>``).

    A unit test cannot reproduce this — pytest has already loaded
    the modules through the test file's own imports. We exercise the
    invariant in a real subprocess so ``sys.modules`` is genuinely
    fresh.

    The subprocess also confirms ``auth.denied`` log emission still
    reaches the test-side ``monkeypatch`` on the shim's ``log_safe``
    (the Lazy-lookup claim: monkeypatches still propagate). That is
    NOT asserted here (no monkeypatch in a subprocess); the in-process
    atom 4 already pins that path. This atom pins the symbol-identity
    invariant only.
    """
    script = textwrap.dedent(
        """
        import sys
        # Clear every app.* entry from sys.modules so the subprocess
        # is genuinely a fresh import state.
        for mod_name in list(sys.modules):
            if mod_name == "app" or mod_name.startswith("app."):
                del sys.modules[mod_name]
        # Import the DI module FIRST.
        from app.core.di import auth_dependencies_di  # noqa: F401
        # THEN import the shim.
        import app.core.auth_dependencies as fresh_shim
        NINE = (
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
        missing = [n for n in NINE if not hasattr(fresh_shim, n)]
        if missing:
            print("MISSING:" + ",".join(missing))
            sys.exit(1)
        not_identity = [
            n
            for n in NINE
            if getattr(fresh_shim, n) is not getattr(auth_dependencies_di, n)
        ]
        if not_identity:
            print("NOT_IDENTITY:" + ",".join(not_identity))
            sys.exit(2)
        # Exercise the consumer import path that triggers the bug
        # in the unfixed code (and that real callers rely on).
        from app.core.auth_dependencies import require_authorized_user
        assert callable(require_authorized_user)
        print("OK")
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"Fresh-process DI-first import regressed the shim re-exports.\n"
        f"stdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}\n"
        f"The di module must defer the shim lookup to call time so the "
        f"shim's star-import runs against the fully-loaded di module."
    )
    assert "OK" in result.stdout, (
        f"Subprocess did not signal success; got stdout={result.stdout!r} "
        f"stderr={result.stderr!r}"
    )
