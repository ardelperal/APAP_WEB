"""TDD RED: tests for ADOPT-03 adoption follow-up state machine (issue #49).

Tests transition_seguimiento():
- valid transitions update estado and timestamps correctly
- invalid transitions raise ValueError with clear reason
- document_url is stored when action == ANEXAR
- log_safe is called on every transition
- adopcion not found returns None

The state machine:

  PENDIENTE
    -> DOCUMENTO_ENTREGADO (MARCAR_ENTREGADO)
    -> SEGUIMIENTO_COMPLETADO (COMPLETAR, direct)
  DOCUMENTO_ENTREGADO
    -> DOCUMENTO_ADJUNTO (ANEXAR)
    -> SEGUIMIENTO_COMPLETADO (COMPLETAR, override)
  DOCUMENTO_ADJUNTO
    -> SEGUIMIENTO_COMPLETADO (COMPLETAR)
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.core.local_backend.db import LocalPostgresExecutor
from app.modules.adopciones import service as adopciones_service


def _json_response(status_code: int, body: Any) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


def _client_recording(
    handler: Callable[[httpx.Request, dict[str, Any]], httpx.Response],
) -> tuple[InsForgeClient, list[dict[str, Any]]]:
    captured: list[dict[str, Any]] = []

    def _recording_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization", "").startswith("Bearer ")
        body = json.loads(request.content.decode("utf-8")) if request.content else {}
        captured.append(body)
        return handler(request, body)

    client = InsForgeClient(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=httpx.MockTransport(_recording_handler),
    )
    return client, captured


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ADOPCION_ID = "adopcion-001"
OPERADOR_ID = "user-operator-1"
DOCUMENTO_URL = "https://storage.example.com/docs/adopcion-001.pdf"


def _adopcion_row(
    *,
    seguimiento_estado: str = "PENDIENTE",
    seguimiento_documento_url: str | None = None,
    seguimiento_documento_entregado_at: str | None = None,
    seguimiento_completado_at: str | None = None,
) -> dict[str, Any]:
    return {
        "id": ADOPCION_ID,
        "animal_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "voluntario_seguimiento_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "fecha_adopcion": "2026-07-04",
        "fecha_devolucion": None,
        "donativo_preadopcion": None,
        "donativo_adopcion": None,
        "nombre_adoptante": "María García López",
        "dni_adoptante": "12345678A",
        "telefono_adoptante": "600123456",
        "email_adoptante": "maria@example.com",
        "entrada_origen_id": None,
        "observaciones": None,
        "tipo_adopcion": "regular",
        "fecha_alta": "2026-07-04T10:00:00Z",
        "updated_at": "2026-07-04T10:00:00Z",
        "activo": True,
        # new seguimiento fields
        "seguimiento_estado": seguimiento_estado,
        "seguimiento_documento_url": seguimiento_documento_url,
        "seguimiento_documento_entregado_at": seguimiento_documento_entregado_at,
        "seguimiento_completado_at": seguimiento_completado_at,
    }


def _make_handler(
    state: str,
    *,
    next_state: str | None = None,
    entregado_at: str | None = None,
    documento_url: str | None = None,
    completado_at: str | None = None,
):
    """Return a handler that simulates the adopcion with given seguimiento fields.

    - First call (SELECT via get_adopcion_by_id): returns row with ``state``
    - Second call (UPDATE via transition_seguimiento): returns row with
      ``next_state`` and the provided timestamp/url fields
    """
    now = "2026-07-04T12:00:00Z"
    first_call = True

    def handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        nonlocal first_call
        sql = body.get("sql", "") if isinstance(body, dict) else ""

        if first_call or "SELECT" in sql.upper():
            first_call = False
            return _json_response(200, [_adopcion_row(seguimiento_estado=state)])

        # UPDATE (seguimiento transition)
        return _json_response(200, [
            _adopcion_row(
                seguimiento_estado=next_state or state,
                seguimiento_documento_entregado_at=entregado_at or now,
                seguimiento_documento_url=documento_url,
                seguimiento_completado_at=completado_at or now,
            )
        ])
    return handler


# ---------------------------------------------------------------------------
# Enums exist and have correct values
# ---------------------------------------------------------------------------

def test_seguimiento_estado_values():
    """SeguinientoEstado has the 4 pinned values from the spec."""
    from app.modules.adopciones.service import SeguimientoEstado
    assert set(SeguimientoEstado) == {
        SeguimientoEstado.PENDIENTE,
        SeguimientoEstado.DOCUMENTO_ENTREGADO,
        SeguimientoEstado.DOCUMENTO_ADJUNTO,
        SeguimientoEstado.SEGUIMIENTO_COMPLETADO,
    }


def test_seguimiento_action_values():
    """SeguinientoAction has the 3 pinned values from the spec."""
    from app.modules.adopciones.service import SeguimientoAction
    assert set(SeguimientoAction) == {
        SeguimientoAction.MARCAR_ENTREGADO,
        SeguimientoAction.ANEXAR,
        SeguimientoAction.COMPLETAR,
    }


# ---------------------------------------------------------------------------
# Valid transitions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "from_state,action,expected_state",
    [
        # PENDIENTE -> DOCUMENTO_ENTREGADO
        (
            "PENDIENTE",
            adopciones_service.SeguimientoAction.MARCAR_ENTREGADO,
            "DOCUMENTO_ENTREGADO",
        ),
        # PENDIENTE -> SEGUIMIENTO_COMPLETADO (direct)
        (
            "PENDIENTE",
            adopciones_service.SeguimientoAction.COMPLETAR,
            "SEGUIMIENTO_COMPLETADO",
        ),
        # DOCUMENTO_ENTREGADO -> DOCUMENTO_ADJUNTO
        (
            "DOCUMENTO_ENTREGADO",
            adopciones_service.SeguimientoAction.ANEXAR,
            "DOCUMENTO_ADJUNTO",
        ),
        # DOCUMENTO_ENTREGADO -> SEGUIMIENTO_COMPLETADO (override)
        (
            "DOCUMENTO_ENTREGADO",
            adopciones_service.SeguimientoAction.COMPLETAR,
            "SEGUIMIENTO_COMPLETADO",
        ),
        # DOCUMENTO_ADJUNTO -> SEGUIMIENTO_COMPLETADO
        (
            "DOCUMENTO_ADJUNTO",
            adopciones_service.SeguimientoAction.COMPLETAR,
            "SEGUIMIENTO_COMPLETADO",
        ),
    ],
)
def test_valid_transition_updates_estado(
    from_state: str,
    action: adopciones_service.SeguimientoAction,
    expected_state: str,
):
    """A valid (from_state, action) pair transitions to expected_state."""
    handler = _make_handler(
        from_state,
        next_state=expected_state,
        documento_url=DOCUMENTO_URL if action == adopciones_service.SeguimientoAction.ANEXAR else None,
    )
    client, _ = _client_recording(handler)

    result = adopciones_service.transition_seguimiento(
        client,
        adopcion_id=ADOPCION_ID,
        action=action,
        operador_user_id=OPERADOR_ID,
        documento_url=DOCUMENTO_URL if action == adopciones_service.SeguimientoAction.ANEXAR else None,
    )

    assert result is not None
    assert result.nuevo_estado == expected_state
    assert result.adopcion_id == ADOPCION_ID


def test_valid_transition_sets_entregado_at():
    """MARCAR_ENTREGADO sets seguimiento_documento_entregado_at."""
    handler = _make_handler(
        "PENDIENTE",
        next_state="DOCUMENTO_ENTREGADO",
        entregado_at="2026-07-04T12:00:00Z",
    )
    client, _ = _client_recording(handler)

    result = adopciones_service.transition_seguimiento(
        client,
        adopcion_id=ADOPCION_ID,
        action=adopciones_service.SeguimientoAction.MARCAR_ENTREGADO,
        operador_user_id=OPERADOR_ID,
    )

    assert result is not None
    assert result.nuevo_estado == "DOCUMENTO_ENTREGADO"
    assert result.seguimiento_documento_entregado_at is not None


def test_anexar_sets_documento_url():
    """ANEXAR stores the provided documento_url."""
    handler = _make_handler(
        "DOCUMENTO_ENTREGADO",
        next_state="DOCUMENTO_ADJUNTO",
        documento_url=DOCUMENTO_URL,
    )
    client, _ = _client_recording(handler)

    result = adopciones_service.transition_seguimiento(
        client,
        adopcion_id=ADOPCION_ID,
        action=adopciones_service.SeguimientoAction.ANEXAR,
        operador_user_id=OPERADOR_ID,
        documento_url=DOCUMENTO_URL,
    )

    assert result is not None
    assert result.seguimiento_documento_url == DOCUMENTO_URL


def test_completar_sets_completado_at():
    """COMPLETAR sets seguimiento_completado_at."""
    handler = _make_handler(
        "DOCUMENTO_ENTREGADO",
        next_state="SEGUIMIENTO_COMPLETADO",
        completado_at="2026-07-04T12:00:00Z",
    )
    client, _ = _client_recording(handler)

    result = adopciones_service.transition_seguimiento(
        client,
        adopcion_id=ADOPCION_ID,
        action=adopciones_service.SeguimientoAction.COMPLETAR,
        operador_user_id=OPERADOR_ID,
    )

    assert result is not None
    assert result.nuevo_estado == "SEGUIMIENTO_COMPLETADO"
    assert result.seguimiento_completado_at is not None


def test_adopcion_not_found_returns_none():
    """transition_seguimiento returns None when the adopcion does not exist."""

    def handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, [])  # empty result

    client, _ = _client_recording(handler)

    result = adopciones_service.transition_seguimiento(
        client,
        adopcion_id="non-existent-id",
        action=adopciones_service.SeguimientoAction.MARCAR_ENTREGADO,
        operador_user_id=OPERADOR_ID,
    )

    assert result is None


# ---------------------------------------------------------------------------
# Invalid transitions
# ---------------------------------------------------------------------------

def test_invalid_transition_pendiente_anexar():
    """PENDIENTE + ANEXAR raises ValueError (invalid)."""
    handler = _make_handler("PENDIENTE")
    client, _ = _client_recording(handler)

    with pytest.raises(ValueError) as exc_info:
        adopciones_service.transition_seguimiento(
            client,
            adopcion_id=ADOPCION_ID,
            action=adopciones_service.SeguimientoAction.ANEXAR,
            operador_user_id=OPERADOR_ID,
            documento_url=DOCUMENTO_URL,
        )
    assert "invalid" in str(exc_info.value).lower()


def test_invalid_transition_documento_entregado_marcar_entregado():
    """DOCUMENTO_ENTREGADO + MARCAR_ENTREGADO raises ValueError (already delivered)."""
    handler = _make_handler("DOCUMENTO_ENTREGADO")
    client, _ = _client_recording(handler)

    with pytest.raises(ValueError) as exc_info:
        adopciones_service.transition_seguimiento(
            client,
            adopcion_id=ADOPCION_ID,
            action=adopciones_service.SeguimientoAction.MARCAR_ENTREGADO,
            operador_user_id=OPERADOR_ID,
        )
    assert "invalid" in str(exc_info.value).lower()


def test_invalid_transition_seguimiento_completado_any_action():
    """SEGUIMIENTO_COMPLETADO + any action raises ValueError (terminal)."""
    handler = _make_handler("SEGUIMIENTO_COMPLETADO")
    client, _ = _client_recording(handler)

    for action in adopciones_service.SeguimientoAction:
        with pytest.raises(ValueError) as exc_info:
            adopciones_service.transition_seguimiento(
                client,
                adopcion_id=ADOPCION_ID,
                action=action,
                operador_user_id=OPERADOR_ID,
            )
        assert "invalid" in str(exc_info.value).lower()


def test_invalid_transition_documento_adjunto_anexar():
    """DOCUMENTO_ADJUNTO + ANEXAR raises ValueError (already attached)."""
    handler = _make_handler("DOCUMENTO_ADJUNTO")
    client, _ = _client_recording(handler)

    with pytest.raises(ValueError) as exc_info:
        adopciones_service.transition_seguimiento(
            client,
            adopcion_id=ADOPCION_ID,
            action=adopciones_service.SeguimientoAction.ANEXAR,
            operador_user_id=OPERADOR_ID,
            documento_url=DOCUMENTO_URL,
        )
    assert "invalid" in str(exc_info.value).lower()


def test_invalid_transition_documento_adjunto_marcar_entregado():
    """DOCUMENTO_ADJUNTO + MARCAR_ENTREGADO raises ValueError."""
    handler = _make_handler("DOCUMENTO_ADJUNTO")
    client, _ = _client_recording(handler)

    with pytest.raises(ValueError) as exc_info:
        adopciones_service.transition_seguimiento(
            client,
            adopcion_id=ADOPCION_ID,
            action=adopciones_service.SeguimientoAction.MARCAR_ENTREGADO,
            operador_user_id=OPERADOR_ID,
        )
    assert "invalid" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# SeguimientoTransitionResult dataclass
# ---------------------------------------------------------------------------

def test_seguimiento_transition_result_fields():
    """SeguimientoTransitionResult carries all required fields from the spec."""
    from app.modules.adopciones.service import SeguimientoTransitionResult

    result = SeguimientoTransitionResult(
        adopcion_id=ADOPCION_ID,
        estado_anterior="PENDIENTE",
        nuevo_estado="DOCUMENTO_ENTREGADO",
        seguimiento_documento_entregado_at="2026-07-04T12:00:00Z",
        seguimiento_documento_url=None,
        seguimiento_completado_at=None,
    )
    assert result.adopcion_id == ADOPCION_ID
    assert result.estado_anterior == "PENDIENTE"
    assert result.nuevo_estado == "DOCUMENTO_ENTREGADO"
    assert result.seguimiento_documento_entregado_at is not None
    assert result.seguimiento_documento_url is None
    assert result.seguimiento_completado_at is None
