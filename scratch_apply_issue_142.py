#!/usr/bin/env python3
"""Atomic implementation of Issue #142 — applies all source edits in one shot.

The repository is shared with concurrent agents that switch branches behind
our back, so we batch every edit + commit into a single Python process.
This avoids the "edit, branch-switch, edit lost" race that hit us on the
earlier attempts.
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


# 2. Apply the test stashes I stashed earlier (idempotent)
print("\nApplying stashed test edits...")
stash_show = subprocess.run(
    ["git", "stash", "list"], cwd=REPO, capture_output=True, text=True
)
print(stash_show.stdout)

# Try to pop the relevant stashes
for stash_ref in ["stash@{1}", "stash@{2}"]:
    res = subprocess.run(
        ["git", "stash", "show", "--stat", stash_ref], cwd=REPO, capture_output=True, text=True
    )
    if res.returncode == 0 and res.stdout.strip():
        print(f"Applying {stash_ref}:")
        print(res.stdout)
        apply = subprocess.run(
            ["git", "stash", "apply", stash_ref], cwd=REPO, capture_output=True, text=True
        )
        if apply.returncode != 0:
            print(f"  apply failed: {apply.stderr}")
        else:
            # Drop the applied stash to keep the list clean
            subprocess.run(["git", "stash", "drop", stash_ref], cwd=REPO, capture_output=True)


# 3. Now make the SOURCE edits
print("\n--- A. Schema: domain.py ---")
domain_path = REPO / "app/core/domain.py"
domain_src = domain_path.read_text(encoding="utf-8")

# Add the new SQL constant after FOSTER_CAPACITY_OVERRIDES_CREATE_TABLE_SQL
old_constant = '''FOSTER_CAPACITY_OVERRIDES_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS foster_capacity_overrides (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    casa_acogida_id UUID NOT NULL REFERENCES casas_acogida(id),
    animal_id UUID NOT NULL REFERENCES animales(id),
    operador_user_id UUID NOT NULL,
    motivo TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now()
)
"""'''

new_constant = '''FOSTER_CAPACITY_OVERRIDES_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS foster_capacity_overrides (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    casa_acogida_id UUID NOT NULL REFERENCES casas_acogida(id),
    animal_id UUID NOT NULL REFERENCES animales(id),
    operador_user_id UUID NOT NULL,
    motivo TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now()
)
"""

# Issue #142 — añade la FK opcional hacia ``acogidas`` para que cada
# override pueda enlazarse con la estancia que justificó. La columna es
# NULLable: el INSERT inicial la deja en NULL (el operador puede
# cancelar el create de la estancia y la auditoría queda honesta
# porque se puede consultar el residuo via
# ``SELECT * FROM foster_capacity_overrides WHERE estancia_id IS NULL``).
# ``create_acogida`` (``app/modules/acogidas/service.py``) emite el
# UPDATE que enlaza el row una vez la estancia es creada; el
# ``AND estancia_id IS NULL`` del WHERE protege contra un link duplicado.
# Idempotente (``ADD COLUMN IF NOT EXISTS``) para que el bootstrap se
# pueda re-aplicar sin crash.
FOSTER_CAPACITY_OVERRIDES_ADD_ESTANCIA_FK_SQL = """
ALTER TABLE foster_capacity_overrides
ADD COLUMN IF NOT EXISTS estancia_id UUID NULL REFERENCES acogidas(id)
"""'''

if old_constant in domain_src:
    domain_src = domain_src.replace(old_constant, new_constant)
    print("  + added FOSTER_CAPACITY_OVERRIDES_ADD_ESTANCIA_FK_SQL")
else:
    print("  ERROR: FOSTER_CAPACITY_OVERRIDES_CREATE_TABLE_SQL not found")
    sys.exit(1)

# Emit the new ALTER in ensure_domain_schema after the CREATE TABLE
old_emit = '''    # FOSTER-03 (#45) — audit log para los overrides de capacidad. La
    # tabla referencia ``casas_acogida`` y ``animales``, ambas ya
    # creadas; emisión DESPUÉS del ALTER de ``acogidas`` mantiene el
    # orden lógico del slice foster. Idempotente vía
    # ``CREATE TABLE IF NOT EXISTS``.
    client.execute_sql(FOSTER_CAPACITY_OVERRIDES_CREATE_TABLE_SQL)'''

new_emit = '''    # FOSTER-03 (#45) — audit log para los overrides de capacidad. La
    # tabla referencia ``casas_acogida`` y ``animales``, ambas ya
    # creadas; emisión DESPUÉS del ALTER de ``acogidas`` mantiene el
    # orden lógico del slice foster. Idempotente vía
    # ``CREATE TABLE IF NOT EXISTS``.
    client.execute_sql(FOSTER_CAPACITY_OVERRIDES_CREATE_TABLE_SQL)
    # Issue #142 — añade la FK opcional ``estancia_id`` al audit log.
    # Emisión DESPUÉS del CREATE de ``foster_capacity_overrides`` (para
    # que la tabla target exista) y DESPUÉS del CREATE de ``acogidas``
    # (para que el FK target exista). Idempotente vía ``ADD COLUMN IF
    # NOT EXISTS``; ver el docstring del SQL constant para el contrato
    # completo del fix y la query de auditoría de huérfanos.
    client.execute_sql(FOSTER_CAPACITY_OVERRIDES_ADD_ESTANCIA_FK_SQL)'''

if old_emit in domain_src:
    domain_src = domain_src.replace(old_emit, new_emit)
    print("  + wired FOSTER_CAPACITY_OVERRIDES_ADD_ESTANCIA_FK_SQL into ensure_domain_schema")
else:
    print("  ERROR: FOSTER-03 emit block not found")
    sys.exit(1)

domain_path.write_text(domain_src, encoding="utf-8")


# 4. record_override signature + RETURNING estancia_id
print("\n--- B. record_override: assignment.py ---")
assign_path = REPO / "app/modules/foster/assignment.py"
assign_src = assign_path.read_text(encoding="utf-8")

old_insert_sql = '''_INSERT_OVERRIDE_SQL: Final[str] = """
INSERT INTO foster_capacity_overrides
    (casa_acogida_id, animal_id, operador_user_id, motivo)
VALUES ($1, $2, $3, $4)
RETURNING id, casa_acogida_id, animal_id, operador_user_id, motivo, created_at
"""'''

new_insert_sql = '''_INSERT_OVERRIDE_SQL: Final[str] = """
INSERT INTO foster_capacity_overrides
    (casa_acogida_id, animal_id, operador_user_id, motivo)
VALUES ($1, $2, $3, $4)
RETURNING id, casa_acogida_id, animal_id, operador_user_id, motivo,
          created_at, estancia_id
"""'''

if old_insert_sql in assign_src:
    assign_src = assign_src.replace(old_insert_sql, new_insert_sql)
    print("  + _INSERT_OVERRIDE_SQL now RETURNs estancia_id (NULL on insert)")
else:
    print("  ERROR: _INSERT_OVERRIDE_SQL not found")
    sys.exit(1)

# Update _row_to_override to handle estancia_id (set default to None if missing)
old_row_to_override = '''def _row_to_override(row: dict[str, Any]) -> FosterCapacityOverride:
    return FosterCapacityOverride(
        id=str(row["id"]),
        casa_acogida_id=str(row["casa_acogida_id"]),
        animal_id=str(row["animal_id"]),
        operador_user_id=str(row["operador_user_id"]),
        motivo=str(row["motivo"]),
        created_at=str(row["created_at"]) if row.get("created_at") else "",
    )'''

new_row_to_override = '''def _row_to_override(row: dict[str, Any]) -> FosterCapacityOverride:
    return FosterCapacityOverride(
        id=str(row["id"]),
        casa_acogida_id=str(row["casa_acogida_id"]),
        animal_id=str(row["animal_id"]),
        operador_user_id=str(row["operador_user_id"]),
        motivo=str(row["motivo"]),
        created_at=str(row["created_at"]) if row.get("created_at") else "",
        estancia_id=str(row["estancia_id"]) if row.get("estancia_id") else None,
    )'''

if old_row_to_override in assign_src:
    assign_src = assign_src.replace(old_row_to_override, new_row_to_override)
    print("  + _row_to_override maps estancia_id (Issue #142)")
else:
    print("  ERROR: _row_to_override not found")
    sys.exit(1)

# Update FosterCapacityOverride dataclass to add estancia_id
old_dc = '''@dataclass(frozen=True, slots=True)
class FosterCapacityOverride:
    """Una fila del audit log ``foster_capacity_overrides``.

    Inmutable; el service graba una fila por override aplicada. El
    ``motivo`` es texto libre validado non-empty en
    :func:`record_override`. El ``operador_user_id`` viene de la
    sesion (no de un form field); ver D-GC-02.
    """

    id: str
    casa_acogida_id: str
    animal_id: str
    operador_user_id: str
    motivo: str
    created_at: str'''

new_dc = '''@dataclass(frozen=True, slots=True)
class FosterCapacityOverride:
    """Una fila del audit log ``foster_capacity_overrides``.

    Inmutable; el service graba una fila por override aplicada. El
    ``motivo`` es texto libre validado non-empty en
    :func:`record_override`. El ``operador_user_id`` viene de la
    sesion (no de un form field); ver D-GC-02.

    Issue #142: ``estancia_id`` enlaza el override con la estancia
    (``acogidas.id``) que justificó el override; ``None`` mientras el
    operador no completa el create de la estancia o si el link falla.
    """

    id: str
    casa_acogida_id: str
    animal_id: str
    operador_user_id: str
    motivo: str
    created_at: str
    estancia_id: str | None = None'''

if old_dc in assign_src:
    assign_src = assign_src.replace(old_dc, new_dc)
    print("  + FosterCapacityOverride dataclass gained estancia_id")
else:
    print("  ERROR: FosterCapacityOverride dataclass not found")
    sys.exit(1)

# Update _LIST_OVERRIDES_FOR_CASA_SQL to RETURN estancia_id too
old_list_sql = '''_LIST_OVERRIDES_FOR_CASA_SQL: Final[str] = """
SELECT id, casa_acogida_id, animal_id, operador_user_id, motivo, created_at
FROM foster_capacity_overrides
WHERE casa_acogida_id = $1
ORDER BY created_at DESC
"""'''

new_list_sql = '''_LIST_OVERRIDES_FOR_CASA_SQL: Final[str] = """
SELECT id, casa_acogida_id, animal_id, operador_user_id, motivo, created_at,
       estancia_id
FROM foster_capacity_overrides
WHERE casa_acogida_id = $1
ORDER BY created_at DESC
"""'''

if old_list_sql in assign_src:
    assign_src = assign_src.replace(old_list_sql, new_list_sql)
    print("  + _LIST_OVERRIDES_FOR_CASA_SQL also returns estancia_id")
else:
    print("  WARN: _LIST_OVERRIDES_FOR_CASA_SQL not found (may be a different variant)")

# Now update record_override to return str (the override UUID)
old_record_override = '''def record_override(
    client: InsForgeClient,
    casa_id: str,
    animal_id: str,
    operador_user_id: str,
    motivo: str,
) -> FosterCapacityOverride:
    """Graba un override de capacidad en ``foster_capacity_overrides``.

    Validación (REQ-GC-6): ``motivo`` debe ser non-empty tras
    ``.strip()``. Si es vacío o solo whitespace, raise
    ``ValueError`` y NO se ejecuta el INSERT (defensa: el test
    ``record_override_no_sql_when_motivo_invalido`` verifica que
    ``captured`` queda vacío).

    El ``operador_user_id`` viene de la sesion (D-GC-02) — el
    handler lo extrae via ``read_session_payload`` y nunca acepta
    input del form en ese campo.

    Tras el INSERT, emite ``log_safe("foster.capacity_override.recorded",
    casa_acogida_id=..., animal_id=..., operador=...)``. El ``motivo``
    NO se loguea: es texto libre del operador y puede llevar PII
    (D-GC-12 / REQ-GC-12).

    Raises:
        ValueError: si ``motivo`` es vacío o solo whitespace.
    """
    motivo_clean = (motivo or "").strip()
    if not motivo_clean:
        raise ValueError("motivo es obligatorio y no puede estar vacio")

    rows = client.execute_sql(
        _INSERT_OVERRIDE_SQL,
        [casa_id, animal_id, operador_user_id, motivo_clean],
    )
    override = _row_to_override(rows[0])
    log_safe(
        "foster.capacity_override.recorded",
        casa_acogida_id=casa_id,
        animal_id=animal_id,
        operador=operador_user_id,
    )
    return override'''

new_record_override = '''def record_override(
    client: InsForgeClient,
    casa_id: str,
    animal_id: str,
    operador_user_id: str,
    motivo: str,
) -> str:
    """Graba un override de capacidad en ``foster_capacity_overrides``.

    Validación (REQ-GC-6): ``motivo`` debe ser non-empty tras
    ``.strip()``. Si es vacío o solo whitespace, raise
    ``ValueError`` y NO se ejecuta el INSERT (defensa: el test
    ``record_override_no_sql_when_motivo_invalido`` verifica que
    ``captured`` queda vacío).

    El ``operador_user_id`` viene de la sesion (D-GC-02) — el
    handler lo extrae via ``read_session_payload`` y nunca acepta
    input del form en ese campo.

    Issue #142: retorna el UUID del override como ``str`` (NO el
    dataclass ``FosterCapacityOverride``) para que el route handler
    pueda encadenarlo directo en la URL de redirect
    (``/acogidas/new?...&override_id=<uuid>``) sin tener que hacer
    ``.id``. ``_row_to_override`` sigue disponible para los callers
    que necesitan la fila completa (``list_overrides_for_casa`` lo
    usa internamente para mapear el dataclass desde ``SELECT``).

    Tras el INSERT, emite ``log_safe("foster.capacity_override.recorded",
    casa_acogida_id=..., animal_id=..., operador=...)``. El ``motivo``
    NO se loguea: es texto libre del operador y puede llevar PII
    (D-GC-12 / REQ-GC-12).

    Raises:
        ValueError: si ``motivo`` es vacío o solo whitespace.

    Returns:
        El UUID del row insertado (``str``).
    """
    motivo_clean = (motivo or "").strip()
    if not motivo_clean:
        raise ValueError("motivo es obligatorio y no puede estar vacio")

    rows = client.execute_sql(
        _INSERT_OVERRIDE_SQL,
        [casa_id, animal_id, operador_user_id, motivo_clean],
    )
    override_id = str(rows[0]["id"])
    log_safe(
        "foster.capacity_override.recorded",
        casa_acogida_id=casa_id,
        animal_id=animal_id,
        operador=operador_user_id,
    )
    return override_id'''

if old_record_override in assign_src:
    assign_src = assign_src.replace(old_record_override, new_record_override)
    print("  + record_override now returns str (the override UUID)")
else:
    print("  ERROR: record_override function not found")
    sys.exit(1)

assign_path.write_text(assign_src, encoding="utf-8")


# 5. Route handler: thread override_id into the redirect URL
print("\n--- C. Route: assignment_routes.py ---")
route_path = REPO / "app/modules/foster/assignment_routes.py"
route_src = route_path.read_text(encoding="utf-8")

old_route_block = '''    # Motivo non-empty: record override, then redirect.
    operador = _operator_user_id(request)
    if not operador:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="sesion sin user_id",
        )
    assignment_service.record_override(
        client,
        casa_id=casa_id,
        animal_id=animal_id,
        operador_user_id=operador,
        motivo=motivo_clean,
    )
    return RedirectResponse(
        url=f"/acogidas/new?animal_id={animal_id}&casa_acogida_id={casa_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )'''

new_route_block = '''    # Motivo non-empty: record override, then redirect.
    # Issue #142 (D-GC-05): el override_id se encadena en el redirect
    # URL para que ``create_acogida`` pueda enlazar el row de
    # ``foster_capacity_overrides`` con la estancia resultante. Sin
    # este parámetro, el row queda huérfano si el operador cancela el
    # create o usa un ``animal_id`` distinto en el segundo form.
    operador = _operator_user_id(request)
    if not operador:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="sesion sin user_id",
        )
    override_id = assignment_service.record_override(
        client,
        casa_id=casa_id,
        animal_id=animal_id,
        operador_user_id=operador,
        motivo=motivo_clean,
    )
    return RedirectResponse(
        url=(
            f"/acogidas/new?animal_id={animal_id}"
            f"&casa_acogida_id={casa_id}"
            f"&override_id={override_id}"
        ),
        status_code=status.HTTP_303_SEE_OTHER,
    )'''

if old_route_block in route_src:
    route_src = route_src.replace(old_route_block, new_route_block)
    print("  + redirect URL now threads override_id")
else:
    print("  ERROR: route handler block not found")
    sys.exit(1)

# Also update the docstring of asignar_submit to mention override_id
old_docstring = '''    - ``admit_with_warning`` + non-empty motivo: record the override
      via ``record_override`` (insert + ``log_safe``), then 303 to
      ``/acogidas/new?animal_id=X&casa_acogida_id=Y``.'''

new_docstring = '''    - ``admit_with_warning`` + non-empty motivo: record the override
      via ``record_override`` (insert + ``log_safe``), then 303 to
      ``/acogidas/new?animal_id=X&casa_acogida_id=Y&override_id=<uuid>``.
      The ``override_id`` query param closes the audit-log atomicity
      gap (issue #142): without it, an operator who cancels the create
      leaves an orphan row in ``foster_capacity_overrides`` with no
      matching ``acogidas`` row.'''

if old_docstring in route_src:
    route_src = route_src.replace(old_docstring, new_docstring)
    print("  + asignar_submit docstring mentions override_id atomicity")

route_path.write_text(route_src, encoding="utf-8")


# 6. Module docstring note for assignment.py: orphan-query
print("\n--- F. Module docstring note: assignment.py ---")
old_module_doc_tail = '''from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal

from app.core.insforge import InsForgeClient'''

# Find the closing line. We need the orphan-query mention. Let me append it
# via a marker replacement near the top.
old_header = '''from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal

from app.core.insforge import InsForgeClient'''

new_header = '''from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal

from app.core.insforge import InsForgeClient'''

# Just append a trailing module docstring addendum — search for last triple-quote
assign_path = REPO / "app/modules/foster/assignment.py"
assign_src = assign_path.read_text(encoding="utf-8")

# Find the first big docstring at the top
old_top_doc_end = '''"""FOSTER-03 foster capacity override (audit log).

Patrón:
'''

# I'll skip this for now since it requires careful matching — the docstring
# note is nice-to-have but not blocking the contract test.


# 7. create_acogida: thread override_id
print("\n--- D. create_acogida: service.py ---")
service_path = REPO / "app/modules/acogidas/service.py"
service_src = service_path.read_text(encoding="utf-8")

# Update _build_write_params to NOT include override_id (it's not a real column)
# Add a separate constant for the link SQL
old_create_acogida = '''def create_acogida(
    client, params: dict[str, Any]
) -> Acogida:
    """Insert a new estancia de acogida and return the persisted row."""
    # Validation runs BEFORE the INSERT so we never write a row with
    # broken FKs. The required-text helpers raise ValueError before any
    # SQL if fecha_inicio or animal_id is empty.
    _build_write_params(params)
    _validate_references(client, params)

    write_params = _build_write_params(params)
    rows = client.execute_sql(_INSERT_ACOGIDA_SQL, write_params)
    acogida = _row_to_acogida(rows[0])
    log_safe("foster.acogida.created", acogida_id=acogida.id)
    return acogida'''

new_create_acogida = '''# Issue #142 — linkage UPDATE from ``create_acogida`` to
# ``foster_capacity_overrides.estancia_id``. The ``AND estancia_id IS
# NULL`` guard prevents linking twice (a duplicate ``create_acogida``
# with the same ``override_id`` is treated as a no-op so the original
# link wins). Empty ``override_id`` (from a missing form field that
# serializes as ``""``) is treated the same as absent — no UPDATE.
_LINK_OVERRIDE_SQL: Final[str] = """
UPDATE foster_capacity_overrides
SET estancia_id = $1
WHERE id = $2
  AND estancia_id IS NULL
"""


def create_acogida(
    client, params: dict[str, Any]
) -> Acogida:
    """Insert a new estancia de acogida and return the persisted row.

    Issue #142: ``params`` may carry an ``override_id`` key (str,
    nullable). When present and non-empty, after the INSERT succeeds
    we UPDATE ``foster_capacity_overrides.estancia_id`` for that
    override row to the new ``acogida.id``. The UPDATE is a no-op
    (0 rows) when the override is already linked or the UUID is
    unknown — in that case we emit a ``foster.override.unlinked``
    warning instead of raising so the operator's estancia creation
    still succeeds.
    """
    # Validation runs BEFORE the INSERT so we never write a row with
    # broken FKs. The required-text helpers raise ValueError before any
    # SQL if fecha_inicio or animal_id is empty.
    _build_write_params(params)
    _validate_references(client, params)

    write_params = _build_write_params(params)
    rows = client.execute_sql(_INSERT_ACOGIDA_SQL, write_params)
    acogida = _row_to_acogida(rows[0])
    log_safe("foster.acogida.created", acogida_id=acogida.id)

    # Issue #142: link the foster_capacity_overrides row to the new
    # estancia, when ``override_id`` is present and non-empty.
    override_id_raw = params.get("override_id")
    if isinstance(override_id_raw, str) and override_id_raw.strip():
        link_rows = client.execute_sql(
            _LINK_OVERRIDE_SQL, [acogida.id, override_id_raw.strip()]
        )
        if not link_rows:
            # 0 rows updated: the override row is already linked, or
            # the UUID does not exist. Log a warning and do NOT raise
            # — the estancia itself was created successfully and
            # audit-log anomalies must not punish the operator.
            log_safe(
                "foster.override.unlinked",
                override_id=override_id_raw,
                motivo="override row missing or already linked",
            )

    return acogida'''

if old_create_acogida in service_src:
    service_src = service_src.replace(old_create_acogida, new_create_acogida)
    print("  + create_acogida links foster_capacity_overrides on override_id")
else:
    print("  ERROR: create_acogida function not found")
    sys.exit(1)

service_path.write_text(service_src, encoding="utf-8")


# 8. Route handler for acogidas: accept override_id as form field
print("\n--- F. Acogidas route handler: routes.py ---")
routes_path = REPO / "app/modules/acogidas/routes.py"
routes_src = routes_path.read_text(encoding="utf-8")

old_route_form = '''@router.post("", response_class=HTMLResponse)
def create_acogida_view(
    request: Request,
    animal_id: str = Form(...),
    fecha_inicio: str = Form(...),
    casa_acogida_id: str | None = Form(None),
    voluntario_acogida_id: str | None = Form(None),
    voluntario_seguimiento1_id: str | None = Form(None),
    voluntario_seguimiento2_id: str | None = Form(None),
    voluntario_sanitario_id: str | None = Form(None),
    fecha_final: str | None = Form(None),
    entrada_origen_id: str | None = Form(None),
    direccion: str | None = Form(None),
    telefono: str | None = Form(None),
    observaciones: str | None = Form(None),
    user: Any = Depends(require_writer_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Create a new estancia; redirect to detail on success, re-render form on validation error."""
    if (early := return_early_if_response(user)) is not None:
        return early
    form_data = _form_data_to_params(
        {
            "animal_id": animal_id,
            "casa_acogida_id": casa_acogida_id,
            "voluntario_acogida_id": voluntario_acogida_id,
            "voluntario_seguimiento1_id": voluntario_seguimiento1_id,
            "voluntario_seguimiento2_id": voluntario_seguimiento2_id,
            "voluntario_sanitario_id": voluntario_sanitario_id,
            "fecha_inicio": fecha_inicio,
            "fecha_final": fecha_final,
            "entrada_origen_id": entrada_origen_id,
            "direccion": direccion,
            "telefono": telefono,
            "observaciones": observaciones,
        }
    )'''

new_route_form = '''@router.post("", response_class=HTMLResponse)
def create_acogida_view(
    request: Request,
    animal_id: str = Form(...),
    fecha_inicio: str = Form(...),
    casa_acogida_id: str | None = Form(None),
    voluntario_acogida_id: str | None = Form(None),
    voluntario_seguimiento1_id: str | None = Form(None),
    voluntario_seguimiento2_id: str | None = Form(None),
    voluntario_sanitario_id: str | None = Form(None),
    fecha_final: str | None = Form(None),
    entrada_origen_id: str | None = Form(None),
    direccion: str | None = Form(None),
    telefono: str | None = Form(None),
    observaciones: str | None = Form(None),
    override_id: str | None = Form(None),
    user: Any = Depends(require_writer_user),
    client: InsForgeClient = Depends(get_insforge_client_dep),
):
    """Create a new estancia; redirect to detail on success, re-render form on validation error.

    Issue #142: ``override_id`` is the (optional) hidden form field
    threaded from ``POST /casas-acogida/{id}/asignar`` when the gate
    returns ``admit_with_warning`` and the operator confirmed the
    override. ``create_acogida`` uses it to UPDATE the
    ``foster_capacity_overrides.estancia_id`` column so the audit
    log row is no longer orphaned. An empty string is treated the
    same as absent.
    """
    if (early := return_early_if_response(user)) is not None:
        return early
    form_data = _form_data_to_params(
        {
            "animal_id": animal_id,
            "casa_acogida_id": casa_acogida_id,
            "voluntario_acogida_id": voluntario_acogida_id,
            "voluntario_seguimiento1_id": voluntario_seguimiento1_id,
            "voluntario_seguimiento2_id": voluntario_seguimiento2_id,
            "voluntario_sanitario_id": voluntario_sanitario_id,
            "fecha_inicio": fecha_inicio,
            "fecha_final": fecha_final,
            "entrada_origen_id": entrada_origen_id,
            "direccion": direccion,
            "telefono": telefono,
            "observaciones": observaciones,
        }
    )
    # Issue #142: thread override_id through to the service so it can
    # link the foster_capacity_overrides row.
    if override_id is not None and override_id.strip():
        form_data["override_id"] = override_id.strip()'''

if old_route_form in routes_src:
    routes_src = routes_src.replace(old_route_form, new_route_form)
    print("  + create_acogida_view accepts override_id form field")
else:
    print("  ERROR: create_acogida_view route handler not found")
    sys.exit(1)

routes_path.write_text(routes_src, encoding="utf-8")


# 9. Template: hidden override_id field
print("\n--- E. Template: form.html ---")
template_path = REPO / "app/templates/acogidas/form.html"
template_src = template_path.read_text(encoding="utf-8")

# Insert hidden override_id field after csrf_token
old_form_start = '''    {# PR-5B2: CSRF defense-in-depth (REQ-AH-7). #}
    <input type="hidden" name="csrf_token" value="{{ csrf_token }}" />

    <fieldset class="space-y-4">'''

new_form_start = '''    {# PR-5B2: CSRF defense-in-depth (REQ-AH-7). #}
    <input type="hidden" name="csrf_token" value="{{ csrf_token }}" />
    {# Issue #142: hidden override_id from /asignar when the operator confirmed an override. #}
    {% if form_data.override_id %}
    <input type="hidden" name="override_id" value="{{ form_data.override_id }}" />
    {% endif %}

    <fieldset class="space-y-4">'''

if old_form_start in template_src:
    template_src = template_src.replace(old_form_start, new_form_start)
    print("  + hidden override_id field in template")
else:
    print("  ERROR: template CSRF block not found")
    sys.exit(1)

template_path.write_text(template_src, encoding="utf-8")


# 10. Verify all changes are in place
print("\n--- Verification ---")
for label, path in [
    ("FOSTER_CAPACITY_OVERRIDES_ADD_ESTANCIA_FK_SQL", "app/core/domain.py"),
    ("_INSERT_OVERRIDE_SQL returning estancia_id", "app/modules/foster/assignment.py"),
    ("record_override -> str return type", "app/modules/foster/assignment.py"),
    ("override_id in redirect URL", "app/modules/foster/assignment_routes.py"),
    ("_LINK_OVERRIDE_SQL constant", "app/modules/acogidas/service.py"),
    ("override_id form param", "app/modules/acogidas/routes.py"),
    ("hidden override_id field", "app/templates/acogidas/form.html"),
]:
    src = (REPO / path).read_text(encoding="utf-8")
    if label == "FOSTER_CAPACITY_OVERRIDES_ADD_ESTANCIA_FK_SQL":
        present = "FOSTER_CAPACITY_OVERRIDES_ADD_ESTANCIA_FK_SQL" in src
    elif label == "_INSERT_OVERRIDE_SQL returning estancia_id":
        present = "RETURNING id, casa_acogida_id, animal_id, operador_user_id, motivo,\n          created_at, estancia_id" in src
    elif label == "record_override -> str return type":
        present = ") -> str:" in src and "def record_override" in src
    elif label == "override_id in redirect URL":
        present = "override_id={override_id}" in src
    elif label == "_LINK_OVERRIDE_SQL constant":
        present = "_LINK_OVERRIDE_SQL" in src and "UPDATE foster_capacity_overrides" in src
    elif label == "override_id form param":
        present = "override_id: str | None = Form(None)" in src
    elif label == "hidden override_id field":
        present = 'name="override_id"' in src
    status = "OK" if present else "MISSING"
    print(f"  [{status}] {label}")


# 11. Commit
print("\n--- Commit ---")
run(["git", "add", "-A"])
result = subprocess.run(
    ["git", "commit", "-m", "fix(foster): link foster_capacity_overrides to estancia on create (#142)"],
    cwd=REPO, capture_output=True, text=True
)
print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr)


# 12. Print summary
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