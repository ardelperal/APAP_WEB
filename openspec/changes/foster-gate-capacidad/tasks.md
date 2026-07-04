# Tasks: FOSTER-03 — Gate de especie + advisory de capacidad con override auditado

skill_resolution: paths-injected

## Phase 1: Schema + Service

### 1.1 Schema: tabla `foster_capacity_overrides`

- [ ] Añadir constante `FOSTER_CAPACITY_OVERRIDES_CREATE_TABLE_SQL` en `app/core/domain.py` (DDL con `id UUID PK`, `casa_acogida_id UUID FK`, `animal_id UUID FK`, `operador_user_id UUID`, `motivo TEXT NOT NULL`, `created_at TIMESTAMP DEFAULT now()`).
- [ ] Llamar la constante en `ensure_domain_schema` DESPUÉS de `ACOGIDAS_ADD_CASA_FK_SQL` (orden: `acogidas` ya tiene FK a `casas_acogida`, y ahora la tabla de overrides puede tener FK a ambas).

### 1.2 Tests domain schema (rojo → verde)

- [ ] `tests/test_domain.py`: añadir `test_foster_capacity_overrides_create_table_sql_constant_exists` que valida la presencia de la constante.
- [ ] `tests/test_domain.py`: actualizar `test_ensure_domain_schema_creates_twelve_tables_plus_one_alter` para esperar 13 CREATE TABLE + 1 ALTER = 14 statements total, con `foster_capacity_overrides` en la posición correcta.

### 1.3 Service: módulo `app/modules/foster/assignment.py` (TDD)

- [ ] Crear dataclasses `AssignmentDecision` y `FosterCapacityOverride` en el módulo.
- [ ] Implementar `evaluate_assignment(client, animal_id, casa_id) -> AssignmentDecision` con:
  - SELECT animal FROM animales WHERE id = $1 AND activo = true (raise ValueError si no).
  - SELECT casa FROM casas_acogida WHERE id = $1 (raise ValueError si no existe o activo = false).
  - Gate de especie: si `casa.especie_preferente is not None AND animal.Especie != casa.especie_preferente` → decision=block, reason con texto claro.
  - Capacity count: SELECT COUNT(*) JOIN acogidas JOIN animales WHERE casa_acogida_id = $1 AND fecha_final IS NULL AND activo = true AND (Especie = especie_preferente OR especie_preferente IS NULL).
  - Si count >= capacidad → decision=admit_with_warning, warnings=(f"capacidad excedida: {count}/{capacidad}",).
  - Else → decision=admit, warnings=().
- [ ] Implementar `record_override(client, casa_id, animal_id, operador_user_id, motivo) -> FosterCapacityOverride`:
  - Validar `motivo` non-empty (raise ValueError si vacío o whitespace).
  - INSERT INTO foster_capacity_overrides (casa_acogida_id, animal_id, operador_user_id, motivo) VALUES ($1, $2, $3, $4) RETURNING ...
  - `log_safe("foster.capacity_override.recorded", casa_acogida_id=..., animal_id=..., operador=...)` (sin el motivo).
  - Retornar `FosterCapacityOverride` dataclass.
- [ ] Implementar `list_overrides_for_casa(client, casa_id) -> list[FosterCapacityOverride]`: SELECT FROM foster_capacity_overrides WHERE casa_acogida_id = $1 ORDER BY created_at DESC.

### 1.4 Tests service (~25 atoms, TDD rojo → verde)

`tests/test_foster_assignment.py` con `httpx.MockTransport` capturando SQL:

- [ ] `test_evaluate_assignment_happy_path_admit` (especie OK, capacidad OK → admit).
- [ ] `test_evaluate_assignment_species_mismatch_block` (animal CANINA, casa FELINA → block con reason claro).
- [ ] `test_evaluate_assignment_casa_cualquier_especie_admit_cualquier_animal` (especie_preferente NULL → admit para cualquier especie).
- [ ] `test_evaluate_assignment_capacity_at_limit_admit_with_warning` (count == capacidad → warning).
- [ ] `test_evaluate_assignment_capacity_exceeded_admit_with_warning` (count > capacidad → warning).
- [ ] `test_evaluate_assignment_animal_no_existe_raise_value_error` (animal_id inexistente → raise).
- [ ] `test_evaluate_assignment_animal_inactivo_raise_value_error` (animal activo = false → raise).
- [ ] `test_evaluate_assignment_casa_no_existe_raise_value_error` (casa_id inexistente → raise).
- [ ] `test_evaluate_assignment_casa_inactiva_raise_value_error` (casa activo = false → raise).
- [ ] `test_evaluate_assignment_count_solo_estancias_de_especie_preferente` (estancia CANINA en casa FELINA no cuenta).
- [ ] `test_evaluate_assignment_count_cualquier_especie_incluye_todas` (casa especie_preferente NULL → cuenta todas las estancias activas).
- [ ] `test_evaluate_assignment_no_cuenta_estancia_cerrada` (fecha_final populated → no cuenta).
- [ ] `test_evaluate_assignment_no_cuenta_estancia_soft_deleted` (activo = false → no cuenta).
- [ ] `test_evaluate_assignment_no_cuenta_otras_casas` (estancia activa en OTRA casa → no cuenta).
- [ ] `test_record_override_happy_inserts_and_returns_dataclass`.
- [ ] `test_record_override_motivo_vacio_raise_value_error_no_sql`.
- [ ] `test_record_override_motivo_whitespace_raise_value_error_no_sql`.
- [ ] `test_record_override_log_safe_emitted_with_operador`.
- [ ] `test_record_override_log_safe_no_incluye_motivo` (PII protection).
- [ ] `test_list_overrides_for_casa_ordenados_por_created_at_desc`.
- [ ] `test_list_overrides_for_casa_sin_overrides_retorna_lista_vacia`.
- [ ] `test_list_overrides_for_casa_no_incluye_otras_casas`.
- [ ] `test_evaluate_assignment_queries_animal_antes_de_casa` (orden de queries para mejor error message).
- [ ] `test_evaluate_assignment_block_reason_incluye_especie_preferente_y_animal`.

## Phase 2: Routes + Templates

### 2.1 Sub-router: `app/modules/foster/assignment_routes.py`

- [ ] Definir `router = APIRouter(prefix="/casas-acogida", tags=["foster"])` (mismo prefijo que `foster_router`).
- [ ] Endpoint `GET /casas-acogida/{casa_id}/asignar`: renderiza `casas_acogida/asignar.html` con `casa` y `form_data` vacío. Carga la casa vía `foster_service.get_casa_acogida_by_id` (404 si no existe).
- [ ] Endpoint `POST /casas-acogida/{casa_id}/asignar`:
  - Llama a `evaluate_assignment` con `animal_id` y `casa_id`.
  - Si `decision = "block"`: 422 + re-render del form con `error = decision.reason`.
  - Si `decision = "admit"`: 303 a `/acogidas/new?animal_id=X&casa_acogida_id=Y`.
  - Si `decision = "admit_with_warning"` con `motivo` non-empty: graba `record_override(...)` + 303.
  - Si `decision = "admit_with_warning"` con `motivo` vacío/whitespace: 422 + re-render con `warning = decision.warnings[0]` y `error = "el motivo es obligatorio para continuar por encima de la capacidad"`.
- [ ] Endpoint `GET /casas-acogida/{casa_id}/overrides`: renderiza `casas_acogida/overrides.html` con `casa` y `overrides` (lista de `FosterCapacityOverride`).
- [ ] Cada handler: `require_authorized_user` dep + `read_session_payload` para extraer `operador_user_id`. Si falta `user_id`, raise HTTPException 401.
- [ ] Cero `client.execute_sql` en el módulo (tests `_NoSqlRouteClient` spy).

### 2.2 Templates

- [ ] `app/templates/casas_acogida/asignar.html`: form con input `name="animal_id"` (UUID, required), input `name="motivo"` (visible solo si hay `warning` en contexto), botón "Evaluar", y vista del resultado (admit/block/admit_with_warning) con copy claro.
- [ ] `app/templates/casas_acogida/overrides.html`: tabla con columnas `created_at`, `animal_id`, `motivo`, `operador_user_id`. Si la lista está vacía, mensaje "sin overrides registrados".
- [ ] Modificar `app/templates/casas_acogida/detail.html`: añadir
  - Bloque "Estancias activas: {count}" (count calculado en route).
  - Botón "Asignar animal" enlazando a `/casas-acogida/{casa.id}/asignar`.
  - Sección "Histórico de overrides" (top 10 de `list_overrides_for_casa`).

### 2.3 Wiring

- [ ] `app/main.py`: importar `assignment_router` desde `app.modules.foster.assignment_routes`. `include_router(assignment_router)` después de `foster_router`.
- [ ] `app/modules/foster/__init__.py`: re-exportar `assignment_service` (NO router — el router se importa directamente en main.py como el resto).

### 2.4 Tests routes (~15 atoms, TDD rojo → verde)

`tests/test_foster_assignment_routes.py` con `AsyncClient` + `dependency_overrides` + `_NoSqlRouteClient`:

- [ ] Auth guard en 3 endpoints (parametrized over method+path).
- [ ] `test_get_asignar_renderiza_form_con_csrf` (GET → 200, contiene `csrf_token`, contiene `animal_id` input).
- [ ] `test_post_asignar_admit_redirect_303_con_query_params` (decision admit → 303 a `/acogidas/new?...`).
- [ ] `test_post_asignar_block_retorna_422_con_error` (decision block → 422 con reason visible).
- [ ] `test_post_asignar_admit_with_warning_con_motivo_graba_override_y_redirect` (graba INSERT + 303).
- [ ] `test_post_asignar_admit_with_warning_sin_motivo_retorna_422_con_warning_visible` (warning visible + mensaje motivo obligatorio).
- [ ] `test_post_asignar_animal_no_existe_retorna_422` (service raise ValueError → route traduce a 422).
- [ ] `test_post_asignar_casa_no_existe_retorna_404` (404 cuando la casa no existe).
- [ ] `test_post_asignar_casa_inactiva_retorna_422` (casa soft-deleted → 422).
- [ ] `test_post_asignar_sin_csrf_retorna_403` (defensa CSRF).
- [ ] `test_get_overrides_renderiza_tabla_con_overrides` (lista llena → tabla).
- [ ] `test_get_overrides_sin_overrides_muestra_mensaje_vacio` (lista vacía → "sin overrides").
- [ ] `test_routes_no_execute_sql_directly` (static check: `assignment_routes.py` no contiene `.execute_sql(`).
- [ ] `test_post_asignar_warning_motivo_whitespace_no_graba_override` (motivo = "   " → 422, NO INSERT).
- [ ] `test_detail_muestra_estancias_activas_y_boton_asignar` (casa detail ahora tiene los nuevos elementos).

## Phase 3: Closeout

### 3.1 XSS audit

- [ ] `tests/test_xss_audit.py`: añadir `casas_acogida/asignar.html` y `casas_acogida/overrides.html` a `TEMPLATE_SPECS` con los `field_paths_to_mutate` apropiados.
- [ ] `tests/test_xss_audit.py`: si `casas_acogida/asignar.html` usa `form_action` interpolado, añadir a `handler_controlled` allowlist con justificación (action es `/casas-acogida/{id}/asignar`, server-generated).

### 3.2 Validación local

- [ ] `python -m pytest -W error::DeprecationWarning --ignore=tests/e2e --deselect tests/test_voluntarios_concurrent.py -q` → 1390+ tests passed, 1 skipped (psycopg), 2 deselected.
- [ ] `ruff check .` → limpio.
- [ ] `python -m build` → OK.

### 3.3 Commit local (NO push)

- [ ] `git add` solo los archivos touched en este slice.
- [ ] `git commit` con subject `feat(foster): gate de especie + advisory de capacidad con override auditado (Refs #45)` y body que cubra: schema, módulo service, sub-router, templates, wiring, tests, SDD, validación, P1 fidelidad.

### 3.4 NO push

- [ ] NO `git push`. NO `gh issue close`. Esperar review ortogonal del orquestador.

### 3.5 Roadmap sync (post-commit, en el mismo stride)

- [ ] `docs/roadmap.md`: quitar #45 de §4 abiertas, añadir a §5-bis cerradas con SHA del commit + test paths.

## Out of scope (deferred)

- Índices adicionales en `acogidas(casa_acogida_id, fecha_final) WHERE activo = true` si la volumetría crece. Hoy innecesario.
- Capacity separada por especie cuando `especie_preferente = NULL` se vuelve patrón común. JSONB o columnas `capacidad_canina`/`capacidad_felina`.
- Roles diferenciados para el gate (admin vs key_user). FOSTER-04+.
- Override por especie (un override de "esta casa admite FELINA pese a preferir CANINA"). Out of scope; el gate de especie es hard block sin override.
- Dropdown visual de selección de animal. Hoy el campo `animal_id` es UUID free-text. Issue futura traerá el módulo de selects.

## Skill Resolution

skill_resolution: paths-injected