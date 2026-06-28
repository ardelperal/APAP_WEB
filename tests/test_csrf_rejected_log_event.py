"""Pin the CSRF rejection event name across the Slice 5 -> Slice 6 swap.

Background:
- PR-5B introduced ``app/core/csrf.py`` with the CSRF middleware and a
  logging placeholder (``self._logger.warning("csrf.rejected", ...)``).
- Slice 6 swaps that placeholder for ``log_safe("csrf.rejected", ...)``
  so the JSON stdout handler captures every rejection with PII
  redaction applied.

Contract: the event name MUST stay ``"csrf.rejected"`` because
downstream dashboards and redaction tests depend on it. Slice 6
touches the call site (function name changes, level changes from
WARNING to INFO, structured fields are first-class kwargs) but
NEVER renames the event.

Similarly, the ``"csrf.disabled"`` event name is preserved when the
feature flag short-circuits the middleware (``Settings.csrf_enabled=False``).
This file pins BOTH event names so a future rename breaks the test.

Spec: ``openspec/changes/hardening-2026-q2/specs/06-structured-logging/spec.md``
(REQ-2, REQ-5). Tasks: T-6.5, T-6.6 (tasks.md).
Round-2 fix SB-5: 12-field redaction list (csrf_token is on it).
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.core.config import get_settings
from app.core.session import session_cookie_name, write_session


class _AnonymousSpy:
    """InsForge stand-in (mirrors ``tests/test_csrf_middleware.py``)."""

    def execute_sql(self, query: str, params: Any = None):  # type: ignore[no-untyped-def]
        if "RETURNING" in query or "INSERT" in query:
            return [
                {
                    "id": "spy-1",
                    "NCHIP": "985112004409871",
                    "NombreAnimal": "Spy",
                    "Especie": "CANINA",
                    "Sexo": "H",
                    "FNacimiento": "2023-04-12",
                    "activo": True,
                }
            ]
        return [{"id": "spy-1"}]

    def __getattr__(self, name: str) -> Any:  # type: ignore[no-untyped-def]
        # Strict mode: unmocked methods surface as test failures (see
        # tests/test_all_post_forms_have_csrf_input.py for the rationale).
        raise NotImplementedError(
            f"_AnonymousSpy.{name} is not mocked. Add an explicit method "
            f"to the spy in this test instead of relying on no-op fallback."
        )


@pytest.fixture
def _bypass_insforge(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.main import app, get_insforge_client

    spy = _AnonymousSpy()
    app.dependency_overrides[get_insforge_client] = lambda: spy
    monkeypatch.setattr(
        "app.modules.animals.routes.get_insforge_client_dep", lambda: spy
    )
    yield
    app.dependency_overrides.pop(get_insforge_client, None)


def _login(client: httpx.AsyncClient) -> None:
    settings = get_settings()
    token = write_session(
        {
            "email": "ana@example.com",
            "rol": "key_user",
            "user_id": "u-ana",
            "is_authorized": True,
            "csrf_token": "session-bound-csrf-token",
        },
        secret=settings.session_secret,
    )
    client.cookies.set(session_cookie_name(), token)


def _animal_form_data() -> dict[str, str]:
    return {
        "NCHIP": "985112004409871",
        "NombreAnimal": "Luna",
        "Especie": "CANINA",
        "Sexo": "H",
        "FNacimiento": "2023-04-12",
    }


# --- csrf.rejected: event name + structured fields ------------------------


async def test_csrf_rejected_event_name_preserved(
    client: httpx.AsyncClient,
    _bypass_insforge: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The Slice 6 swap to ``log_safe`` MUST keep the ``csrf.rejected`` event name.

    Captures the structured log emitted on a rejected POST and asserts:
    1. The event name is ``"csrf.rejected"`` (not "csrf_failed", etc.).
    2. The structured fields carry ``path``, ``reason``, ``method`` so
       operators can route the rejection to the right handler.
    3. The sensitive session-bound csrf_token MUST NOT leak (it is in
       REDACTED_FIELDS per round-2 fix SB-5).
    """
    _login(client)

    with caplog.at_level("INFO", logger="app"):
        response = await client.post(
            "/animales",
            data=_animal_form_data(),
            follow_redirects=False,
        )

    assert response.status_code == 403

    rejection_records = [
        rec for rec in caplog.records if getattr(rec, "event", None) == "csrf.rejected"
    ]
    assert rejection_records, (
        f"expected a csrf.rejected log record, got events: "
        f"{[getattr(r, 'event', None) for r in caplog.records]}"
    )
    record = rejection_records[0]
    # Operator-facing fields MUST be present and literal.
    assert record.path == "/animales"
    assert record.method == "POST"
    assert record.reason in {"missing_token", "token_mismatch", "missing_session"}
    # Level: log_safe emits INFO (operators see auth/route events on
    # the default INFO filter). The pre-PR-6 code emitted WARNING;
    # dashboards filter on the event name, not the level.
    assert record.levelno == 20  # logging.INFO


async def test_csrf_rejected_does_not_leak_session_token_in_log(
    client: httpx.AsyncClient,
    _bypass_insforge: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Round-2 fix SB-5: the redacted session-bound csrf_token MUST NOT
    appear on the rejection log even though it is the reason the
    rejection fired. REQ-2 closed-list invariant for csrf_token.
    """
    _login(client)

    with caplog.at_level("INFO", logger="app"):
        await client.post(
            "/animales",
            data=_animal_form_data(),
            follow_redirects=False,
        )

    record = next(
        rec for rec in caplog.records if getattr(rec, "event", None) == "csrf.rejected"
    )
    # No literal token in any log attribute.
    record_dump = str(record.__dict__)
    assert "session-bound-csrf-token" not in record_dump
    # The csrf_token field, if present, is redacted (not literal).
    token_value = getattr(record, "csrf_token", None)
    if token_value is not None:
        assert token_value == "[REDACTED]"


# --- csrf.disabled: operator debugging signal -----------------------------


async def test_csrf_disabled_event_name_emitted_when_feature_flag_off(
    client: httpx.AsyncClient,
    _bypass_insforge: None,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When ``Settings.csrf_enabled=False`` the middleware MUST log
    ``csrf.disabled`` so operators can tell during an incident whether
    the defense is live or feature-flagged off.

    This test monkey-patches the middleware's feature-flag check via
    env var + cache clear. The middleware is registered at module import
    only when the flag is True; to exercise the disabled path we
    instantiate a fresh ``CsrfMiddleware`` over the captured app and
    invoke ``dispatch`` directly with a non-safe method.
    """
    from starlette.requests import Request

    from app.core.csrf import CsrfMiddleware

    class _OkResponse:
        status_code = 200

    async def _call_next(_: Request):  # pragma: no cover - never awaited on disabled
        return _OkResponse()

    # Build a minimal request whose method is non-safe.
    request = Request(
        scope={
            "type": "http",
            "method": "POST",
            "path": "/animales",
            "raw_path": b"/animales",
            "query_string": b"",
            "headers": [(b"host", b"testserver")],
            "client": ("testserver", 50000),
            "server": ("testserver", 80),
            "scheme": "http",
            "root_path": "",
        }
    )

    middleware = CsrfMiddleware(app=None)  # type: ignore[arg-type]

    # Force the settings flag off and clear the lru_cache so
    # ``get_settings()`` returns the new value.
    monkeypatch.setenv("APAP_CSRF_ENABLED", "false")
    get_settings.cache_clear()

    with caplog.at_level("INFO", logger="app"):
        await middleware.dispatch(request, _call_next)

    disabled_records = [
        rec for rec in caplog.records if getattr(rec, "event", None) == "csrf.disabled"
    ]
    assert disabled_records, (
        f"expected a csrf.disabled log record, got events: "
        f"{[getattr(r, 'event', None) for r in caplog.records]}"
    )
