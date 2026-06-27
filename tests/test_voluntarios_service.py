"""Service-layer tests for ``app.modules.voluntarios.service`` related to the
TOCTOU fix on ``deactivate_voluntario`` (Slice 7, hardening-2026-q2).

The contract under test:

- ``deactivate_voluntario(client, voluntario_id) -> bool`` runs a SINGLE
  ``UPDATE ... WHERE id = $1 AND activo = true RETURNING id`` and returns
  ``True`` if a row was deactivated, ``False`` if the id does not exist
  OR the row was already inactive.

- The handler invokes the service exactly once (no SELECT-then-UPDATE
  TOCTOU window). The route-level coverage of that contract lives in
  ``tests/test_voluntarios_routes.py``.

Idempotency contract: calling ``deactivate_voluntario`` twice with the
same id yields ``True`` then ``False`` (because the second call sees
``activo = false`` and the ``WHERE activo = true`` filter excludes it).
PostgreSQL's row lock guarantees that two truly concurrent calls
produce the same outcome (one winner, one loser). The mock-based
idempotency test below verifies the contract independently of any
real PostgreSQL connection.

Reference: ``openspec/changes/hardening-2026-q2/specs/07-toctou-fix/spec.md``
REQ-1 (single SQL, no SELECT previo) and REQ-2 (404 semantics).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.core.insforge import InsForgeClient
from app.modules.voluntarios import service as voluntarios_service


def _json_response(status_code: int, body: Any) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


def _client_recording(handler) -> tuple[InsForgeClient, list[dict[str, Any]]]:
    """Build a recording ``InsForgeClient`` that captures every ``execute_sql`` call.

    The handler receives the raw ``httpx.Request`` and returns a
    pre-canned ``httpx.Response``. Tests inspect ``captured`` to assert
    on the SQL emitted and the parameters passed.
    """
    captured: list[dict[str, Any]] = []

    def _recording_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else {}
        captured.append(body)
        return handler(request, body)

    client = InsForgeClient(
        base_url="https://example.insforge.app",
        service_key="ik_test",
        transport=httpx.MockTransport(_recording_handler),
    )
    return client, captured


# --- deactivate_voluntario -----------------------------------------------


def test_deactivate_idempotent() -> None:
    """Calling ``deactivate_voluntario`` twice yields ``True`` then ``False``.

    Mirrors the production semantic: the second call sees
    ``activo = false`` and the ``WHERE activo = true`` filter excludes
    the row, so ``RETURNING id`` is empty.

    Implementation note: the handler will translate the second ``False``
    into a 404 (see ``tests/test_voluntarios_routes.py``). This test
    exercises only the service layer.
    """
    call_count = {"n": 0}

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        call_count["n"] += 1
        # First call: row is active -> UPDATE matches -> RETURNING id.
        # Second call: row is inactive -> WHERE activo = true excludes -> [].
        if call_count["n"] == 1:
            return _json_response(200, [{"id": "v-1"}])
        return _json_response(200, [])

    client, captured = _client_recording(_handler)

    first = voluntarios_service.deactivate_voluntario(client, "v-1")
    second = voluntarios_service.deactivate_voluntario(client, "v-1")
    client.close()

    assert first is True
    assert second is False
    # Exactly two SQL calls; the second one is the same statement.
    assert len(captured) == 2
    for entry in captured:
        assert "UPDATE voluntarios" in entry["query"]
        assert "SET activo = false" in entry["query"]
        assert "RETURNING id" in entry["query"]
        assert "WHERE id = $1 AND activo = true" in entry["query"]
        assert entry["params"] == ["v-1"]


def test_deactivate_voluntario_no_existe_retorna_False() -> None:
    """``deactivate_voluntario`` returns ``False`` when the id does not exist.

    The mock returns an empty list to simulate the
    ``UPDATE ... RETURNING id`` finding zero rows.
    """

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, [])

    client, _ = _client_recording(_handler)
    result = voluntarios_service.deactivate_voluntario(client, "no-such-id")
    client.close()

    assert result is False


def test_deactivate_voluntario_emite_una_sola_sentencia_atomica() -> None:
    """Service must emit exactly ONE ``UPDATE ... RETURNING`` per call.

    Regression guard against re-introducing the SELECT-then-UPDATE
    TOCTOU pattern inside the service (the audit finding at
    ``engram:14518`` flagged the route-level pattern; this test makes
    sure the service does not regress to it either).
    """

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, [{"id": "v-1"}])

    client, captured = _client_recording(_handler)
    voluntarios_service.deactivate_voluntario(client, "v-1")
    client.close()

    assert len(captured) == 1, (
        "deactivate_voluntario debe emitir exactamente UN execute_sql; "
        f"se emitieron {len(captured)}"
    )
    sql = captured[0]["query"]
    # NO SELECT previo. UPDATE atomico con RETURNING y filtro activo=true.
    assert "SELECT" not in sql
    assert "UPDATE voluntarios" in sql
    assert "SET activo = false" in sql
    assert "WHERE id = $1 AND activo = true" in sql
    assert "RETURNING id" in sql


@pytest.mark.parametrize(
    "voluntario_id",
    ["abc-123", "uuid-con-guiones-y-todo", "12345678-1234-1234-1234-123456789012"],
    ids=["short-id", "long-slug", "uuid"],
)
def test_deactivate_voluntario_pasa_id_como_primer_parametro(voluntario_id: str) -> None:
    """The service binds ``voluntario_id`` to ``$1`` (positional, not string-concat)."""

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        return _json_response(200, [{"id": voluntario_id}])

    client, captured = _client_recording(_handler)
    voluntarios_service.deactivate_voluntario(client, voluntario_id)
    client.close()

    assert captured[0]["params"] == [voluntario_id]
