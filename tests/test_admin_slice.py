"""Tests for the hexagonal admin slice.

The new slice
(``app/core/application/admin/``,
``app/core/adapters/admin_template_adapter.py``,
``app/core/di/admin_di.py``) is the pattern-defining slice for
admin-style use cases: routes that compose an existing data port
(``AuthUsersPort`` from PR #414) with a typed renderer
(``AdminTemplateAdapter``).

These tests pin the **new** pattern at three levels:

1. **Use cases** — thin delegators that compose ``AuthUsersPort``
   plus an existing auth use case for validation. Tests use a
   recording fake implementing the Protocol; the assertions are on
   which port methods get called and on the response shape (render
   panel vs redirect).
2. **Adapter** — ``AdminTemplateAdapter.render_panel`` is a thin
   Jinja wrapper. Tests render against a real ``Jinja2Templates``
   instance with a minimal ``admin.html`` so the projection from
   :class:`AuthorizedUser` to the template dict is exercised end-to-end.
3. **DI helper** — the per-request ``AdminTemplateAdapter`` resolves
   ``Jinja2Templates`` from ``app.state.templates``.

The legacy ``app/core/admin_handlers.py`` now imports the use cases
and keeps the ``register_admin_routes(app, templates)`` signature so
``app/main.py`` is unchanged; the existing route-level tests in
``tests/test_admin.py`` and ``tests/test_admin_handler_sync.py``
remain the regression net.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from starlette.requests import Request

from app.core.adapters.admin_template_adapter import AdminTemplateAdapter
from app.core.application.admin.add_user import add_user as add_user_uc
from app.core.application.admin.deactivate_user import (
    deactivate_user as deactivate_user_uc,
)
from app.core.application.admin.render_admin_panel import (
    render_admin_panel as render_panel_uc,
)
from app.core.di.admin_di import get_admin_template_adapter
from app.core.domain.auth.rol import Rol
from app.core.domain.auth.user import AuthorizedUser
from app.core.ports.admin_port import AdminPanelContext

# --- recording fake ---------------------------------------------------------


class _RecordingPort:
    """Recording fake that implements :class:`AuthUsersPort`.

    Records every call so the use-case tests can assert which port
    methods the admin use cases reach and what arguments they pass.
    Returns canned values for the read paths; the auth use cases drive
    the write paths (``add_authorized_user``, ``deactivate_authorized_user``)
    by raising or returning based on the per-test configuration.
    """

    def __init__(
        self,
        users: list[AuthorizedUser] | None = None,
    ) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self._users = users or []
        self._email_taken = False
        self._deactivate_raises: Exception | None = None

    def set_email_taken(self, taken: bool) -> None:
        self._email_taken = taken

    def set_deactivate_raises(self, exc: Exception | None) -> None:
        self._deactivate_raises = exc

    # Protocol methods -------------------------------------------------------

    def ensure_schema_and_seed(self, initial_admin_email: str) -> None:
        self.calls.append(("ensure_schema_and_seed", (initial_admin_email,)))

    def get_user_by_email(self, email: str) -> AuthorizedUser | None:
        self.calls.append(("get_user_by_email", (email,)))
        for user in self._users:
            if user.email == email:
                return user
        return None

    def check_email_taken(self, email: str) -> bool:
        self.calls.append(("check_email_taken", (email,)))
        return self._email_taken

    def list_authorized_users(self) -> list[AuthorizedUser]:
        self.calls.append(("list_authorized_users", ()))
        return list(self._users)

    def add_authorized_user(
        self,
        email: str,
        rol: Rol,
        added_by: str,
    ) -> AuthorizedUser:
        self.calls.append(("add_authorized_user", (email, rol.value, added_by)))
        new_user = AuthorizedUser(
            id="u-new",
            email=email,
            rol=rol,
            active=True,
            added_by=added_by,
        )
        self._users.append(new_user)
        return new_user

    def get_user_by_id(self, user_id: str) -> AuthorizedUser | None:
        self.calls.append(("get_user_by_id", (user_id,)))
        for user in self._users:
            if user.id == user_id:
                return user
        return None

    def deactivate_authorized_user(self, user_id: str) -> AuthorizedUser:
        self.calls.append(("deactivate_authorized_user", (user_id,)))
        if self._deactivate_raises is not None:
            raise self._deactivate_raises
        for user in self._users:
            if user.id == user_id:
                # Return a deactivated copy (immutable entity, so build new).
                deactivated = AuthorizedUser(
                    id=user.id,
                    email=user.email,
                    rol=user.rol,
                    active=False,
                    added_by=user.added_by,
                    added_at=user.added_at,
                )
                self._users = [
                    deactivated if existing.id == user_id else existing
                    for existing in self._users
                ]
                return deactivated
        from app.core.application.auth._domain_errors import UserNotFoundError

        raise UserNotFoundError(f"user not found: {user_id!r}")


def _user(
    id_: str = "u-1",
    email: str = "ana@example.com",
    rol: Rol = Rol.KEY_USER,
    active: bool = True,
) -> AuthorizedUser:
    return AuthorizedUser(id=id_, email=email, rol=rol, active=active)


def _current_user() -> dict:
    return {"user_id": "u-dev", "email": "dev@example.com", "rol": "developer"}


def _make_adapter() -> tuple[AdminTemplateAdapter, str]:
    """Build a real ``AdminTemplateAdapter`` over a temp directory.

    The minimal ``admin.html`` reads ``app_name``, ``current_user.email``,
    ``u.email``, and ``roles`` so the tests can assert the projection
    end-to-end without depending on the production template.
    """
    tmp = tempfile.mkdtemp()
    template = Path(tmp) / "admin.html"
    template.write_text(
        "<h1>{{ app_name }}</h1>"
        "<p>{{ current_user.email }}</p>"
        "<ul>{% for u in users %}<li>{{ u.email }}</li>{% endfor %}</ul>"
        "{% if error_message %}<div class=\"alert\">{{ error_message }}</div>{% endif %}"
        "{% for r in roles %}<span>{{ r }}</span>{% endfor %}",
        encoding="utf-8",
    )
    from fastapi.templating import Jinja2Templates

    templates = Jinja2Templates(directory=str(tmp))
    return AdminTemplateAdapter(templates), tmp


def _fake_request() -> Request:
    """Build a Starlette ``Request`` with the bare minimum scope."""
    return Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/admin",
            "headers": [],
            "query_string": b"",
        }
    )


# --- use cases --------------------------------------------------------------


def test_render_admin_panel_calls_list_authorized_users() -> None:
    """The use case fetches the user list and renders the panel."""
    port = _RecordingPort(users=[_user(), _user(id_="u-2", email="eva@example.com")])
    adapter, _ = _make_adapter()
    response = render_panel_uc(
        port,
        adapter,
        _fake_request(),
        current_user=_current_user(),
        app_name="TestApp",
        roles=frozenset({"key_user", "developer"}),
    )
    body = response.body.decode("utf-8")
    assert "ana@example.com" in body
    assert "eva@example.com" in body
    assert "TestApp" in body
    assert port.calls == [("list_authorized_users", ())]


def test_render_admin_panel_propagates_error_flash() -> None:
    """The use case passes the flash payload into the template context."""
    port = _RecordingPort(users=[])
    adapter, _ = _make_adapter()
    response = render_panel_uc(
        port,
        adapter,
        _fake_request(),
        current_user=_current_user(),
        app_name="TestApp",
        roles=frozenset({"key_user"}),
        error_message="cannot deactivate the last active developer",
        error_type="danger",
    )
    assert "cannot deactivate the last active developer" in response.body.decode("utf-8")


def test_add_user_redirects_with_flash_on_invalid_role() -> None:
    """An invalid rol short-circuits before any port call."""
    port = _RecordingPort(users=[])
    adapter, _ = _make_adapter()
    response = add_user_uc(
        port,
        adapter,
        _fake_request(),
        current_user=_current_user(),
        email="new@example.com",
        rol="hacker",
        app_name="TestApp",
        roles=frozenset({"key_user", "developer"}),
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/admin"
    # No port interaction (the role check rejects before any SQL).
    assert port.calls == []


def test_add_user_calls_auth_use_case_on_valid_role() -> None:
    """A valid rol triggers the auth use case's INSERT path."""
    port = _RecordingPort(users=[_user(email="new@example.com", rol=Rol.KEY_USER)])
    adapter, _ = _make_adapter()
    response = add_user_uc(
        port,
        adapter,
        _fake_request(),
        current_user=_current_user(),
        email="new@example.com",
        rol="key_user",
        app_name="TestApp",
        roles=frozenset({"key_user", "developer"}),
    )
    # Success path re-renders the panel (no redirect) — preserves legacy behavior.
    assert response.status_code == 200
    # The auth use case called the duplicate pre-check and the INSERT.
    called = [name for name, _ in port.calls]
    assert "check_email_taken" in called
    assert "add_authorized_user" in called


def test_add_user_renders_panel_with_error_on_duplicate_email() -> None:
    """A duplicate email short-circuits the auth use case and re-renders with flash."""
    port = _RecordingPort(users=[_user(email="existing@example.com", rol=Rol.KEY_USER)])
    port.set_email_taken(True)
    adapter, _ = _make_adapter()
    response = add_user_uc(
        port,
        adapter,
        _fake_request(),
        current_user=_current_user(),
        email="existing@example.com",
        rol="key_user",
        app_name="TestApp",
        roles=frozenset({"key_user", "developer"}),
    )
    # Duplicate path re-renders admin.html with the error message — never 302.
    assert response.status_code == 200
    assert "email already authorized" in response.body.decode("utf-8")
    # The duplicate pre-check returned True so the auth use case never
    # reached the INSERT port method.
    called = [name for name, _ in port.calls]
    assert "add_authorized_user" not in called


def test_add_user_propagates_legacy_form_field_name_rol() -> None:
    """The route handler accepts the legacy ``rol`` form-field name verbatim.

    ``app/templates/admin.html`` still ships ``name="role"`` (a known
    pre-existing mismatch); the route parameter is ``rol`` so legacy
    callers (and tests) pass ``rol=`` directly. The admin use case
    must accept that key. This test pins the contract.
    """
    port = _RecordingPort(users=[_user()])
    adapter, _ = _make_adapter()
    response = add_user_uc(
        port,
        adapter,
        _fake_request(),
        current_user=_current_user(),
        email="new@example.com",
        rol="  key_user  ",  # whitespace stripped by the auth use case
        app_name="TestApp",
        roles=frozenset({"key_user", "developer"}),
    )
    assert response.status_code == 200


def test_deactivate_user_redirects_on_success() -> None:
    """A successful deactivation returns the legacy 302 redirect."""
    port = _RecordingPort(users=[_user(id_="u-1", email="a@b.com", rol=Rol.KEY_USER)])
    adapter, _ = _make_adapter()
    response = deactivate_user_uc(
        port,
        adapter,
        _fake_request(),
        current_user=_current_user(),
        user_id="u-1",
        app_name="TestApp",
        roles=frozenset({"key_user", "developer"}),
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/admin"
    # Only one deactivate call; no list_authorized_users (success path skips the re-render).
    called = [name for name, _ in port.calls]
    assert called == ["deactivate_authorized_user"]


def test_deactivate_user_renders_panel_with_flash_on_last_developer() -> None:
    """A last-developer guard error re-renders the panel with the flash."""
    from app.core.application.auth._domain_errors import LastActiveDeveloperError

    port = _RecordingPort(users=[])
    port.set_deactivate_raises(LastActiveDeveloperError("cannot deactivate the last active developer"))
    adapter, _ = _make_adapter()
    response = deactivate_user_uc(
        port,
        adapter,
        _fake_request(),
        current_user=_current_user(),
        user_id="only-dev",
        app_name="TestApp",
        roles=frozenset({"key_user", "developer"}),
    )
    # Error path re-renders admin.html (status 200), NOT a redirect (302).
    assert response.status_code == 200
    assert "cannot deactivate the last active developer" in response.body.decode("utf-8")


# --- template adapter -------------------------------------------------------


def test_admin_template_adapter_renders_with_sorted_roles() -> None:
    """The adapter passes a sorted roles list to the template."""
    adapter, _ = _make_adapter()
    response = adapter.render_panel(
        AdminPanelContext(
            request=_fake_request(),
            current_user=_current_user(),
            users=[],
            app_name="TestApp",
            roles=frozenset({"writer", "key_user", "developer"}),
        )
    )
    body = response.body.decode("utf-8")
    # Sorted lexicographically; "developer" < "key_user" < "writer".
    dev_idx = body.find("developer")
    key_idx = body.find("key_user")
    writer_idx = body.find("writer")
    assert 0 <= dev_idx < key_idx < writer_idx


def test_admin_template_adapter_projects_users_via_to_dict() -> None:
    """The adapter calls :meth:`AuthorizedUser.to_dict` so the template sees the legacy dict shape."""
    adapter, _ = _make_adapter()
    user = _user(email="ana@example.com")
    response = adapter.render_panel(
        AdminPanelContext(
            request=_fake_request(),
            current_user=_current_user(),
            users=[user],
            app_name="TestApp",
            roles=frozenset({"key_user"}),
        )
    )
    assert "ana@example.com" in response.body.decode("utf-8")


def test_admin_template_adapter_omits_flash_when_message_is_none() -> None:
    """No ``error_message`` key in the rendered HTML when the message is absent."""
    adapter, _ = _make_adapter()
    response = adapter.render_panel(
        AdminPanelContext(
            request=_fake_request(),
            current_user=_current_user(),
            users=[],
            app_name="TestApp",
            roles=frozenset({"key_user"}),
        )
    )
    body = response.body.decode("utf-8")
    # The flash slot is an ``{% if error_message %}`` block; the rendered
    # HTML has no ``alert`` div when the message is ``None``.
    assert "alert" not in body or '<div class="alert">' not in body


# --- DI helper --------------------------------------------------------------


def test_get_admin_template_adapter_resolves_app_state_templates() -> None:
    """The DI helper wraps the per-app ``Jinja2Templates`` from ``app.state.templates``."""
    from fastapi.templating import Jinja2Templates

    app = FastAPI()
    tmp = tempfile.mkdtemp()
    Path(tmp, "admin.html").write_text("<h1>OK</h1>", encoding="utf-8")
    app.state.templates = Jinja2Templates(directory=str(tmp))

    req = type("R", (), {"app": app})()
    gen = get_admin_template_adapter(req)
    try:
        adapter = next(gen)
        assert isinstance(adapter, AdminTemplateAdapter)
        assert adapter._templates is app.state.templates  # noqa: SLF001
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


# --- architectural rule pins -------------------------------------------------


def test_admin_application_layer_does_not_import_insforge() -> None:
    """Rule §31: the admin application layer depends on the Protocol, not on a concrete client."""
    import importlib

    admin_pkg = importlib.import_module("app.core.application.admin")
    for module_name in admin_pkg.__all__:
        module = __import__(
            f"app.core.application.admin.{module_name}",
            fromlist=["_"],
        )
        for attr in module.__dict__.values():
            attr_module = getattr(attr, "__module__", "") or ""
            assert "insforge" not in attr_module.lower() or attr_module.startswith(
                "tests"
            ), (
                f"admin application module {module_name!r} leaked InsForge "
                f"import from {attr_module!r}"
            )


def test_admin_adapter_does_not_import_insforge() -> None:
    """The admin template adapter is a Jinja-only wrapper — no InsForge coupling."""
    import app.core.adapters.admin_template_adapter as adapter_module

    for attr in adapter_module.__dict__.values():
        attr_module = getattr(attr, "__module__", "") or ""
        assert "insforge" not in attr_module.lower(), (
            f"admin template adapter leaked InsForge import from {attr_module!r}"
        )


def test_admin_di_does_not_export_domain_or_port() -> None:
    """The admin DI helper exposes ONLY FastAPI dependencies — domain entities and
    ports stay behind the ``get_<slice>_port`` factories."""
    import importlib

    di_pkg = importlib.import_module("app.core.di")
    admin_di = importlib.import_module("app.core.di.admin_di")

    # The admin DI is slice-scoped: it only exports its own dependency.
    assert admin_di.__all__ == ["get_admin_template_adapter"]

    # The package re-exports each slice's DI factory. None of those
    # factories are domain entities or Protocol classes.
    for export_name in di_pkg.__all__:
        attr = getattr(di_pkg, export_name)
        attr_module = getattr(attr, "__module__", "") or ""
        assert "core.domain" not in attr_module, (
            f"app.core.di leaked a domain import via {export_name!r} from {attr_module!r}"
        )
        assert "core.ports" not in attr_module, (
            f"app.core.di leaked a port import via {export_name!r} from {attr_module!r}"
        )


def test_admin_handlers_does_not_import_insforge_client() -> None:
    """Rule §1 + §31: the admin route layer must not reach for ``LocalPostgresExecutor``.

    The route handlers now compose ``AuthUsersPort`` (via DI) instead of
    importing the concrete backend client directly. This test pins the
    invariant at module level so a future refactor that re-introduces
    the legacy coupling fails the build.
    """
    import app.core.admin_handlers as admin_handlers_module

    source = Path(admin_handlers_module.__file__).read_text(encoding="utf-8")
    assert "from app.core.local_backend.db import LocalPostgresExecutor" not in source, (
        "app/core/admin_handlers.py must NOT import LocalPostgresExecutor; "
        "compose AuthUsersPort via Depends(get_auth_users_port) instead."
    )
    assert "LocalPostgresExecutor," not in source or "LocalPostgresExecutor, Depends" not in source, (
        "app/core/admin_handlers.py must NOT declare a `client: LocalPostgresExecutor` "
        "parameter; route handlers compose AuthUsersPort instead."
    )
