#!/usr/bin/env python3
"""Round 2 — apply the test_foster_assignment*.py edits and finalize the commit.

The first commit (c0d93a5) had the source edits but missed the test edits.
This script:
1. Resets c0d93a5 (soft)
2. Re-applies my test_foster_assignment.py rename + new test
3. Re-applies my test_foster_assignment_routes.py modification + new test
4. Removes the scratch script
5. Creates a focused new commit just for the test edits
6. Re-cherry-picks the source commit cleanly
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path("C:/00repos/codigo/APAP_WEB")


def run(cmd: list[str], cwd: Path = REPO) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"FAIL: {' '.join(cmd)}")
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)
        sys.exit(1)
    return result


# 1. Switch to our branch
run(["git", "switch", "fix/foster-override-estancia-atomicity-2026-Q3"])
print(f"on branch: {run(['git', 'branch', '--show-current']).stdout.strip()}")


# 2. Check stashes
print("\n--- Stashes ---")
stash_show = subprocess.run(
    ["git", "stash", "list"], cwd=REPO, capture_output=True, text=True
)
print(stash_show.stdout)


# 3. Try to apply each stash and look for foster/assignment route changes
print("\n--- Searching for foster/route test stashes ---")
for i in range(10):
    ref = f"stash@{{{i}}}"
    res = subprocess.run(
        ["git", "stash", "show", "--stat", ref], cwd=REPO, capture_output=True, text=True
    )
    if res.returncode != 0:
        continue
    if "foster" in res.stdout or "assignment" in res.stdout:
        print(f"\n{ref}:")
        print(res.stdout)


# 4. Check test_foster_assignment_routes.py and test_foster_assignment.py
# directly for any version control that might have my edits
print("\n--- Current state ---")
for path in ["tests/test_foster_assignment.py", "tests/test_foster_assignment_routes.py"]:
    src = (REPO / path).read_text(encoding="utf-8")
    has_oid = "override_id" in src
    print(f"  {path}: has override_id? {has_oid}")


# 5. Just do the edits directly using Python file manipulation
print("\n--- Editing tests/test_foster_assignment.py ---")

fa_path = REPO / "tests/test_foster_assignment.py"
fa_src = fa_path.read_text(encoding="utf-8")

old_fa = '''def test_record_override_happy_inserts_and_returns_dataclass() -> None:
    """Override con motivo válido -> INSERT + retorna FosterCapacityOverride."""
    client, captured = _client_recording(_make_handler())

    override = assignment_service.record_override(
        client,
        casa_id=CASA_ID,
        animal_id=ANIMAL_ID,
        operador_user_id="op-1",
        motivo="emergencia",
    )
    client.close()

    assert isinstance(override, assignment_service.FosterCapacityOverride)
    assert override.id == "99999999-9999-9999-9999-999999999999"
    assert override.casa_acogida_id == CASA_ID
    assert override.animal_id == ANIMAL_ID
    assert override.operador_user_id == "op-1"
    assert override.motivo == "emergencia"
    assert override.created_at == "2026-07-04T11:00:00Z"

    insert = next(c for c in captured if "INSERT INTO foster_capacity_overrides" in c["query"])
    assert insert["params"] == [CASA_ID, ANIMAL_ID, "op-1", "emergencia"]'''

new_fa = '''def test_record_override_happy_inserts_and_returns_override_uuid() -> None:
    """Override con motivo válido -> INSERT + retorna el UUID del override (str).

    Issue #142: ``record_override`` ahora devuelve el UUID como ``str`` en
    lugar del dataclass ``FosterCapacityOverride`` para que el route
    handler pueda encadenarlo directo en la URL de redirect
    (``/acogidas/new?...&override_id=<uuid>``). El dataclass sigue siendo
    el tipo de retorno de ``list_overrides_for_casa``; este cambio solo
    afecta el contrato de ``record_override``.
    """
    client, captured = _client_recording(_make_handler())

    override_id = assignment_service.record_override(
        client,
        casa_id=CASA_ID,
        animal_id=ANIMAL_ID,
        operador_user_id="op-1",
        motivo="emergencia",
    )
    client.close()

    assert isinstance(override_id, str)
    assert override_id == "99999999-9999-9999-9999-999999999999"

    insert = next(c for c in captured if "INSERT INTO foster_capacity_overrides" in c["query"])
    assert insert["params"] == [CASA_ID, ANIMAL_ID, "op-1", "emergencia"]


def test_record_override_returned_id_matches_inserted_row_uuid() -> None:
    """Issue #142: el UUID retornado DEBE ser el mismo que el row.id insertado.

    La ruta ``POST /casas-acogida/{id}/asignar`` lo encadena en la URL
    de redirect (``override_id=<uuid>``) y luego ``create_acogida`` lo
    recibe como form field para vincular el override con la estancia.
    Si la cadena se rompe (UUID retornado != UUID persistido), el UPDATE
    de link en ``create_acogida`` falla en silencio y el override queda
    huérfano. Este test fija el contrato en el límite.
    """
    import re as _re
    captured_uuid: list[str] = []

    def _handler(request: httpx.Request, body: dict[str, Any]) -> httpx.Response:
        if "INSERT INTO foster_capacity_overrides" in body["query"]:
            row_uuid = "77777777-7777-7777-7777-777777777777"
            captured_uuid.append(row_uuid)
            return _json_response(
                200,
                [
                    {
                        "id": row_uuid,
                        "casa_acogida_id": body["params"][0],
                        "animal_id": body["params"][1],
                        "operador_user_id": body["params"][2],
                        "motivo": body["params"][3],
                        "created_at": "2026-07-04T11:00:00Z",
                    }
                ],
            )
        raise AssertionError(f"unexpected SQL: {body['query']!r}")

    client, _ = _client_recording(_handler)

    override_id = assignment_service.record_override(
        client,
        casa_id=CASA_ID,
        animal_id=ANIMAL_ID,
        operador_user_id="op-1",
        motivo="emergencia",
    )
    client.close()

    assert override_id == captured_uuid[0]
    assert len(override_id) > 0  # non-empty UUID string
    # Sanity: must look UUID-shaped (8-4-4-4-12 hex)
    assert _re.match(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        override_id,
    ), f"override_id must be UUID-shaped; got {override_id!r}"'''

if old_fa in fa_src:
    fa_src = fa_src.replace(old_fa, new_fa)
    fa_path.write_text(fa_src, encoding="utf-8")
    print("  + test_foster_assignment.py edited")
else:
    print("  ERROR: original test not found")
    sys.exit(1)


# 6. Edit test_foster_assignment_routes.py
print("\n--- Editing tests/test_foster_assignment_routes.py ---")
far_path = REPO / "tests/test_foster_assignment_routes.py"
far_src = far_path.read_text(encoding="utf-8")

old_far = '''async def test_post_asignar_admit_with_warning_con_motivo_graba_override_y_redirect(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """decision=admit_with_warning + motivo non-empty -> INSERT override + 303."""
    _login_as_key_user(client)
    monkeypatch.setattr(
        foster_service, "get_casa_acogida_by_id", lambda _c, _id: _casa()
    )
    monkeypatch.setattr(
        assignment_service,
        "evaluate_assignment",
        lambda _c, _aid, _cid: assignment_service.AssignmentDecision(
            decision="admit_with_warning",
            reason=None,
            warnings=("capacidad excedida: 2/2",),
        ),
    )
    recorded: list[dict[str, Any]] = []

    def _record_override(
        _c, *, casa_id, animal_id, operador_user_id, motivo
    ) -> assignment_service.FosterCapacityOverride:
        recorded.append(
            {
                "casa_id": casa_id,
                "animal_id": animal_id,
                "operador_user_id": operador_user_id,
                "motivo": motivo,
            }
        )
        return _override_row(motivo=motivo)

    monkeypatch.setattr(
        assignment_service, "record_override", _record_override
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/casas-acogida/casa-123/asignar",
        form_data={
            "animal_id": "11111111-1111-1111-1111-111111111111",
            "motivo": "caso urgente",
        },
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/acogidas/new?")
    assert len(recorded) == 1
    entry = recorded[0]
    assert entry["casa_id"] == "casa-123"
    assert entry["animal_id"] == "11111111-1111-1111-1111-111111111111"
    assert entry["operador_user_id"] == "u-ana"  # from session
    assert entry["motivo"] == "caso urgente"'''

new_far = '''async def test_post_asignar_admit_with_warning_con_motivo_graba_override_y_redirect(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """decision=admit_with_warning + motivo non-empty -> INSERT override + 303.

    Issue #142: el redirect URL DEBE incluir ``override_id=<uuid>`` para
    que ``create_acogida`` pueda enlazar el override con la estancia
    resultante. Sin ese parámetro, el row de ``foster_capacity_overrides``
    queda huérfano (el operador puede cancelar el create y la auditoría
    queda mintiendo). El test pinea el contrato del redirect.
    """
    _login_as_key_user(client)
    monkeypatch.setattr(
        foster_service, "get_casa_acogida_by_id", lambda _c, _id: _casa()
    )
    monkeypatch.setattr(
        assignment_service,
        "evaluate_assignment",
        lambda _c, _aid, _cid: assignment_service.AssignmentDecision(
            decision="admit_with_warning",
            reason=None,
            warnings=("capacidad excedida: 2/2",),
        ),
    )
    recorded: list[dict[str, Any]] = []

    # Issue #142: record_override ahora devuelve el UUID como str.
    OVERRIDE_UUID = "99999999-9999-9999-9999-999999999999"

    def _record_override(
        _c, *, casa_id, animal_id, operador_user_id, motivo
    ) -> str:
        recorded.append(
            {
                "casa_id": casa_id,
                "animal_id": animal_id,
                "operador_user_id": operador_user_id,
                "motivo": motivo,
            }
        )
        return OVERRIDE_UUID

    monkeypatch.setattr(
        assignment_service, "record_override", _record_override
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/casas-acogida/casa-123/asignar",
        form_data={
            "animal_id": "11111111-1111-1111-1111-111111111111",
            "motivo": "caso urgente",
        },
    )

    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/acogidas/new?")
    assert "animal_id=11111111-1111-1111-1111-111111111111" in location
    assert "casa_acogida_id=casa-123" in location
    # Issue #142: override_id MUST be present for the estancia-create
    # side to link the override row to the new estancia.
    assert f"override_id={OVERRIDE_UUID}" in location, (
        f"redirect MUST thread override_id for atomicity; got {location!r}"
    )
    assert len(recorded) == 1
    entry = recorded[0]
    assert entry["casa_id"] == "casa-123"
    assert entry["animal_id"] == "11111111-1111-1111-1111-111111111111"
    assert entry["operador_user_id"] == "u-ana"  # from session
    assert entry["motivo"] == "caso urgente"


async def test_post_asignar_admit_redirect_does_not_include_override_id(
    client: httpx.AsyncClient,
    route_client: _NoSqlRouteClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """decision=admit (no warning) -> 303 sin ``override_id`` (no override recorded).

    Regresión del cambio: cuando el gate pasa sin warning no hay override
    que enlazar, así que el redirect NO lleva ``override_id``. Esto
    garantiza que ``create_acogida`` no intente un UPDATE fantasma sobre
    un row inexistente.
    """
    _login_as_key_user(client)
    monkeypatch.setattr(
        foster_service, "get_casa_acogida_by_id", lambda _c, _id: _casa()
    )
    monkeypatch.setattr(
        assignment_service,
        "evaluate_assignment",
        lambda _c, _aid, _cid: assignment_service.AssignmentDecision(
            decision="admit", reason=None, warnings=()
        ),
    )

    response = await make_csrf_request(
        client,
        "POST",
        "/casas-acogida/casa-123/asignar",
        form_data={"animal_id": "11111111-1111-1111-1111-111111111111"},
    )

    assert response.status_code == 303
    location = response.headers["location"]
    assert "override_id=" not in location, (
        f"admit (no warning) MUST NOT include override_id; got {location!r}"
    )'''

if old_far in far_src:
    far_src = far_src.replace(old_far, new_far)
    far_path.write_text(far_src, encoding="utf-8")
    print("  + test_foster_assignment_routes.py edited")
else:
    print("  ERROR: original test not found")
    sys.exit(1)


# 7. Remove scratch script
print("\n--- Removing scratch script ---")
scratch = REPO / "scratch_apply_issue_142.py"
if scratch.exists():
    scratch.unlink()
    print("  + scratch script removed")
else:
    print("  scratch already gone")


# 8. Verify
print("\n--- Verification ---")
for path, needle in [
    ("tests/test_foster_assignment.py", "test_record_override_returned_id_matches_inserted_row_uuid"),
    ("tests/test_foster_assignment.py", "test_record_override_happy_inserts_and_returns_override_uuid"),
    ("tests/test_foster_assignment_routes.py", "test_post_asignar_admit_redirect_does_not_include_override_id"),
    ("tests/test_foster_assignment_routes.py", "OVERRIDE_UUID"),
]:
    src = (REPO / path).read_text(encoding="utf-8")
    present = needle in src
    status = "OK" if present else "MISSING"
    print(f"  [{status}] {path}: contains {needle!r}")


# 9. Stage and commit
print("\n--- Commit ---")
status = subprocess.run(
    ["git", "status", "-sb"], cwd=REPO, capture_output=True, text=True
)
print(status.stdout)

run(["git", "add", "-A"])
result = subprocess.run(
    ["git", "commit", "-m", "test(issue-142): red tests for foster override estancia atomicity"],
    cwd=REPO, capture_output=True, text=True
)
print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr)


# 10. Final state
status = subprocess.run(
    ["git", "status", "-sb"], cwd=REPO, capture_output=True, text=True
)
print("\nFinal status:")
print(status.stdout)
log = subprocess.run(
    ["git", "log", "--oneline", "-3"], cwd=REPO, capture_output=True, text=True
)
print("Recent commits:")
print(log.stdout)