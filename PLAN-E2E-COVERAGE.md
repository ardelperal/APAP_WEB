# Plan de cobertura E2E

> **Estado**: propuesta. No se han creado tests todavía.
> **Alcance**: inventario exhaustivo de la superficie HTTP del proyecto y plan priorizado para ampliar `tests/e2e/` con cobertura end-to-end ejecutada por Playwright.

## Resumen ejecutivo

El proyecto cuenta con **ocho ficheros E2E en `tests/e2e/`**. Cubren exclusivamente la superficie pública y una única página autenticada a través del mock `app/core/e2e_auth.py`.

La superficie CRUD completa de los quince módulos de dominio —**noventa y tres rutas**— **no tiene cobertura E2E**.

El desbloqueo técnico ya está disponible. El mock `GET /e2e/login` de la issue #598 permite mintear una cookie con rol `developer` mediante la cabecera `X-E2E-Secret`.

Este plan propone **veintidós ficheros de tests E2E nuevos** para cubrir:

1. CRUD completo de cada router (`list` → `new` → `create` → `detail` → `edit` → `update` → `delete`).
2. Reglas de negocio (transiciones de estado de adopción, capacidad de casas de acogida, conflictos de material, cesión con `entrada_id` único).
3. Gates de autorización (lectura abierta, escritura restringida a `writer+`, panel `developer`-only).
4. Casos límite (404, 409, 422, CSRF inválido).

---

## Estado actual

### Inventario de tests E2E existentes

| Fichero | Tests | Rutas tocadas | Cobertura |
|---|---|---|---|
| `tests/e2e/test_login_form.py` | 6 | `GET /login` | Estructura del formulario (CSRF, `method=post`, `action=/auth/google`, campos email/password, submit accesible, `<title>` no vacío) |
| `tests/e2e/test_logout.py` | 3 | `GET /logout` | Redirección 302, expiración de la cookie `apap_session`, redirección posterior a `/login` para rutas protegidas |
| `tests/e2e/test_landing.py` | 8 | `GET /`, `GET /login`, `GET /unauthorized`, `GET /healthz` | Auth-guard anónimo, color primario `#0A91EB`, enlace «Entrar con Gmail», nav top, logo APAP, footer `#076FB8`, JSON de `/healthz` |
| `tests/e2e/test_public_redirects.py` | 5 | `GET /`, `GET /animales`, `GET /logout`, `GET /auth/google`, `GET /healthz` | Sentinels de redirección para rutas protegidas, contrato 503/302 de `/auth/google` |
| `tests/e2e/test_nav_layout.py` | 5 | `GET /login` (plantilla base) | Sentinels responsive en 375 px, 768 px y 1280 px; ausencia de scroll horizontal; nav apilado en mobile |
| `tests/e2e/test_layout_responsive_extended.py` | 5 | `GET /login` (plantilla base) | Sentinels responsive en 1024 px y 1920 px |
| `tests/e2e/test_admin_authenticated.py` | 3 | `GET /admin` | Mock OAuth `GET /e2e/login` con `X-E2E-Secret`, cookie persistente, gate `require_developer_user_redirect` |
| `tests/e2e/test_security_headers.py` | 4 | `GET /healthz`, `GET /login`, `GET /admin`, `GET /static/css/output.css` | Cabecera CSP literal en respuestas, sin violaciones en consola |

> Total: **39 tests E2E** que cubren ocho rutas públicas y una única superficie autenticada (el panel `/admin`).

### Mapa de rutas por módulo

Conteo de endpoints declarados con `@router.<método>` en cada fichero de rutas, ordenado por prefijo del router.

| Módulo | Prefijo | Fichero | Endpoints | Auth mínima |
|---|---|---|---|---|
| `animals` | `/animales` | `app/modules/animals/routes.py` | 11 | `READ_ANIMALES` |
| `entradas` | `/entradas` | `app/modules/entradas/routes.py` | 7 | `READ_ENTRADAS` |
| `entradas (batch)` | `/entradas/batch` | `app/modules/entradas/batch_routes.py` | 5 | `require_authorized_user` |
| `foster (casas)` | `/casas-acogida` | `app/modules/foster/routes.py` | 7 | `READ_CASAS_ACOGIDA` |
| `foster (asignación)` | `/casas-acogida` | `app/modules/foster/assignment_routes.py` | 3 | `require_writer_user` |
| `acogidas` | `/acogidas` | `app/modules/acogidas/routes.py` | 8 | `READ_ACOGIDAS` |
| `cesiones` | `/cesiones` | `app/modules/cesiones/routes.py` | 2 | `READ_CESIONES` |
| `voluntarios` | `/voluntarios` | `app/modules/voluntarios/routes.py` | 7 | `READ_VOLUNTARIOS` |
| `adopciones` | `/adopciones` | `app/modules/adopciones/routes.py` | 8 | `require_authorized_user` |
| `sanidad` | `/sanidad` | `app/modules/sanidad/routes.py` | 7 | `require_authorized_user` |
| `sanidad (batch)` | `/sanidad` | `app/modules/sanidad/batch_routes.py` | 2 | `require_writer_user` |
| `tareas` | `/tareas` | `app/modules/tasks/routes.py` | 5 | `require_authorized_user` |
| `salud` | `/terapias`, `/recomendaciones` | `app/modules/salud/routes.py` | 11 | `READ_SALUD` / `WRITE_SALUD` |
| `materiales` | `/materiales` | `app/modules/materiales/routes.py` | 7 | `require_authorized_user` |
| `materiales (junction)` | `/acogidas/.../materiales` | `app/modules/materiales/acogida_routes.py` | 3 | `require_authorized_user` |
| `admin` | `/admin` | `app/core/admin_handlers.py` | 3 | `require_developer_user_redirect` |
| `auth` | `/login`, `/auth/google`, `/auth/callback`, `/logout` | `app/core/auth_flow.py` | 4 | público |
| `e2e mock` | `/e2e/login` | `app/core/e2e_auth.py` | 1 | cabecera `X-E2E-Secret` |
| **Total dominio** | — | — | **93** | — |

### Convenciones del suite E2E actual

| Convención | Localización |
|---|---|
| Fixture `browser_context` (un contexto por test, cookies aisladas) | `tests/e2e/conftest.py` |
| Fixture `page` (page atada al contexto) | `tests/e2e/conftest.py` |
| Auto-skip si falta Chromium o `APAP_E2E_SKIP=1` | `tests/e2e/conftest.py` |
| Preflight `_skip_if_oauth_not_configured(page, base_url)` cuando `/login` devuelve 503 | replicado en `test_login_form.py`, `test_logout.py`, `test_public_redirects.py`, `test_landing.py`, `test_nav_layout.py`, `test_security_headers.py` |
| Fixture `authenticated_page` que mintea sesión con `GET /e2e/login` + `X-E2E-Secret` | `tests/e2e/test_admin_authenticated.py` (plantilla a copiar) |
| `BASE_URL` configurable con `APAP_E2E_BASE_URL` (default `http://127.0.0.1:8000`) | `tests/e2e/conftest.py` |
| `LAYOUT_TOLERANCE_PX = 4` para asserts de bounding box | `tests/e2e/test_nav_layout.py` |

---

## Mapa de cobertura por ruta

Cada fila enumera un endpoint. La columna «E2E» indica si existe cobertura actual (`parcial`, `total`, `ninguna`). La columna «Prioridad» aplica los criterios descritos en la sección siguiente.

| Ruta | Método | Módulo | Auth | E2E | Prioridad |
|---|---|---|---|---|---|
| `/` | GET | core | sesión | parcial (redirect) | P2 |
| `/healthz` | GET | core | público | total | — |
| `/unauthorized` | GET | core | sesión | parcial (redirect) | P2 |
| `/login` | GET | core | público | total | — |
| `/auth/google` | GET | core | público | parcial | P2 |
| `/auth/callback` | GET | core | público | ninguna | P1 |
| `/logout` | GET | core | público | total | — |
| `/admin` | GET | admin | developer | parcial (gate) | P1 |
| `/admin/users` | POST | admin | developer | ninguna | P1 |
| `/admin/users/{user_id}/deactivate` | POST | admin | developer | ninguna | P1 |
| `/e2e/login` | GET | e2e_auth | secret | parcial (admin) | — |
| `/animales` | GET | animals | READ | parcial (redirect) | P0 |
| `/animales/search` | GET | animals | READ | ninguna | P2 |
| `/animales/new` | GET | animals | WRITE | ninguna | P0 |
| `/animales` | POST | animals | WRITE | ninguna | P0 |
| `/animales/{animal_id}` | GET | animals | READ | ninguna | P0 |
| `/animales/{animal_id}/salud/resumen` | GET | animals | READ | ninguna | P2 |
| `/animales/{animal_id}/edit` | GET | animals | WRITE | ninguna | P0 |
| `/animales/{animal_id}/update` | POST | animals | WRITE | ninguna | P0 |
| `/animales/{animal_id}/delete` | POST | animals | DELETE | ninguna | P0 |
| `/animales/{animal_id}/chip` | PATCH | animals | WRITE | ninguna | P1 |
| `/animales/{animal_id}/foto` | GET | animals | READ | ninguna | P2 |
| `/entradas` | GET | entradas | READ | ninguna | P0 |
| `/entradas/new` | GET | entradas | READ | ninguna | P0 |
| `/entradas` | POST | entradas | WRITE | ninguna | P0 |
| `/entradas/{entrada_id}` | GET | entradas | READ | ninguna | P0 |
| `/entradas/{entrada_id}/edit` | GET | entradas | WRITE | ninguna | P0 |
| `/entradas/{entrada_id}/update` | POST | entradas | WRITE | ninguna | P0 |
| `/entradas/{entrada_id}/delete` | POST | entradas | DELETE | ninguna | P0 |
| `/entradas/batch/new` | GET | entradas | sesión | ninguna | P1 |
| `/entradas/batch` | POST | entradas | writer | ninguna | P1 |
| `/entradas/batch/{batch_id}` | GET | entradas | sesión | ninguna | P1 |
| `/entradas/batch/{batch_id}/commit` | POST | entradas | writer | ninguna | P1 |
| `/entradas/batch/{batch_id}/cancel` | POST | entradas | writer | ninguna | P1 |
| `/casas-acogida` | GET | foster | READ | ninguna | P0 |
| `/casas-acogida/new` | GET | foster | READ | ninguna | P0 |
| `/casas-acogida` | POST | foster | WRITE | ninguna | P0 |
| `/casas-acogida/{casa_id}` | GET | foster | READ | ninguna | P0 |
| `/casas-acogida/{casa_id}/edit` | GET | foster | WRITE | ninguna | P0 |
| `/casas-acogida/{casa_id}/update` | POST | foster | WRITE | ninguna | P0 |
| `/casas-acogida/{casa_id}/delete` | POST | foster | DELETE | ninguna | P0 |
| `/casas-acogida/{casa_id}/asignar` | GET | foster | writer | ninguna | P0 (gate) |
| `/casas-acogida/{casa_id}/asignar` | POST | foster | writer | ninguna | P0 (gate) |
| `/casas-acogida/{casa_id}/overrides` | GET | foster | sesión | ninguna | P1 |
| `/acogidas` | GET | acogidas | READ | ninguna | P0 |
| `/acogidas/new` | GET | acogidas | READ | ninguna | P0 |
| `/acogidas` | POST | acogidas | WRITE | ninguna | P0 |
| `/acogidas/{acogida_id}` | GET | acogidas | READ | ninguna | P0 |
| `/acogidas/{acogida_id}/edit` | GET | acogidas | WRITE | ninguna | P0 |
| `/acogidas/{acogida_id}/update` | POST | acogidas | WRITE | ninguna | P0 |
| `/acogidas/{acogida_id}/close` | POST | acogidas | WRITE | ninguna | P0 |
| `/acogidas/{acogida_id}/delete` | POST | acogidas | DELETE | ninguna | P0 |
| `/cesiones/new` | GET | cesiones | READ | ninguna | P1 |
| `/cesiones` | POST | cesiones | WRITE | ninguna | P1 |
| `/voluntarios` | GET | voluntarios | READ | ninguna | P0 |
| `/voluntarios/new` | GET | voluntarios | READ | ninguna | P0 |
| `/voluntarios` | POST | voluntarios | WRITE | ninguna | P0 |
| `/voluntarios/{voluntario_id}` | GET | voluntarios | READ | ninguna | P0 |
| `/voluntarios/{voluntario_id}/roles/add` | POST | voluntarios | WRITE | ninguna | P1 |
| `/voluntarios/{voluntario_id}/roles/remove` | POST | voluntarios | WRITE | ninguna | P1 |
| `/voluntarios/{voluntario_id}/deactivate` | POST | voluntarios | WRITE | ninguna | P1 |
| `/adopciones` | GET | adopciones | sesión | ninguna | P0 |
| `/adopciones/new` | GET | adopciones | sesión | ninguna | P0 |
| `/adopciones` | POST | adopciones | writer | ninguna | P0 |
| `/adopciones/{adopcion_id}` | GET | adopciones | sesión | ninguna | P0 |
| `/adopciones/{adopcion_id}/edit` | GET | adopciones | writer | ninguna | P0 |
| `/adopciones/{adopcion_id}/update` | POST | adopciones | writer | ninguna | P0 |
| `/adopciones/{adopcion_id}/delete` | POST | adopciones | writer | ninguna | P0 |
| `/adopciones/{adopcion_id}/seguimiento` | PATCH | adopciones | writer | ninguna | P0 (state machine) |
| `/sanidad` | GET | sanidad | sesión | ninguna | P0 |
| `/sanidad/new` | GET | sanidad | sesión | ninguna | P0 |
| `/sanidad` | POST | sanidad | writer | ninguna | P0 |
| `/sanidad/{actuacion_id}` | GET | sanidad | sesión | ninguna | P0 |
| `/sanidad/{actuacion_id}/edit` | GET | sanidad | writer | ninguna | P0 |
| `/sanidad/{actuacion_id}/update` | POST | sanidad | writer | ninguna | P0 |
| `/sanidad/{actuacion_id}/delete` | POST | sanidad | writer | ninguna | P0 |
| `/sanidad/batch/new` | GET | sanidad | sesión | ninguna | P1 |
| `/sanidad/actuaciones/batch` | POST | sanidad | writer | ninguna | P1 |
| `/tareas` | GET | tareas | sesión | ninguna | P1 |
| `/tareas` | POST | tareas | sesión | ninguna | P1 |
| `/tareas/{tarea_id}` | GET | tareas | sesión | ninguna | P1 |
| `/tareas/{tarea_id}/asignar` | POST | tareas | sesión | ninguna | P1 |
| `/tareas/{tarea_id}/cerrar` | POST | tareas | sesión | ninguna | P1 |
| `/terapias` | GET | salud | READ | ninguna | P0 |
| `/terapias/new` | GET | salud | READ | ninguna | P0 |
| `/terapias` | POST | salud | WRITE | ninguna | P0 |
| `/terapias/{terapia_id}` | GET | salud | READ | ninguna | P0 |
| `/terapias/{terapia_id}/edit` | GET | salud | WRITE | ninguna | P0 |
| `/terapias/{terapia_id}/update` | POST | salud | WRITE | ninguna | P0 |
| `/terapias/{terapia_id}/delete` | POST | salud | WRITE | ninguna | P0 |
| `/terapias/{terapia_id}/recomendaciones` | GET | salud | READ | ninguna | P0 |
| `/terapias/{terapia_id}/recomendaciones` | POST | salud | WRITE | ninguna | P0 |
| `/recomendaciones/{recomendacion_id}` | PATCH | salud | WRITE | ninguna | P1 |
| `/recomendaciones/{recomendacion_id}` | DELETE | salud | WRITE | ninguna | P1 |
| `/materiales` | GET | materiales | sesión | ninguna | P0 |
| `/materiales/new` | GET | materiales | sesión | ninguna | P0 |
| `/materiales` | POST | materiales | writer | ninguna | P0 |
| `/materiales/{material_id}` | GET | materiales | sesión | ninguna | P0 |
| `/materiales/{material_id}/edit` | GET | materiales | writer | ninguna | P0 |
| `/materiales/{material_id}/edit` | POST | materiales | writer | ninguna | P0 |
| `/materiales/{material_id}/deactivate` | POST | materiales | writer | ninguna | P0 |
| `/acogidas/{estancia_id}/materiales` | GET | materiales junction | sesión | ninguna | P1 |
| `/acogidas/{estancia_id}/materiales` | POST | materiales junction | writer | ninguna | P1 |
| `/acogidas/{estancia_id}/materiales/{junction_id}/delete` | POST | materiales junction | writer | ninguna | P1 |

**Síntesis**: ochenta y tres rutas sin cobertura E2E, distribuidas en quince módulos y un panel de administración.

---

## Criterios de priorización

| Prioridad | Definición | Ejemplos |
|---|---|---|
| **P0** | CRUD completo de cada router (listar, crear, ver, editar, borrar) más las reglas de negocio críticas y los gates de autorización que las protegen. Su regresión rompe el flujo del operador. | CRUD de `animals`, `entradas`, `acogidas`, `casas-acogida`, `voluntarios`, `adopciones`, `sanidad`, `salud`, `materiales`; gate de asignación `foster`; PATCH de seguimiento `adopciones`. |
| **P1** | Flujos batch, junctions, transiciones de estado secundarias y endpoints administrativos. Su regresión degrada la experiencia sin bloquear la operación. | Batch `entradas` y `sanidad`, junction `materiales ↔ estancia`, overrides, roles de voluntario, panel admin. |
| **P2** | Endpoints de búsqueda, JSON internos, vistas de detalle fotográfico y resumen sanitario. Su regresión afecta a la información mostrada pero no a la operación. | `/animales/search`, `/animales/{id}/salud/resumen`, `/animales/{id}/foto`. |

---

## Brecha de cobertura priorizada

### P0 — Crítico (primera iteración)

| Módulo | Rutas a cubrir | Notas de diseño |
|---|---|---|
| `animals` | `list`, `new`, `create`, `detail`, `edit`, `update`, `delete`, `chip` PATCH | CRUD con campos obligatorios `nombre`, `chip`, `especie`, `sexo`, `fecha_nacimiento`. Verificar redirect 303 a `detail` tras `create`, 422 si falta un campo requerido, soft-delete redirige a `list`. |
| `entradas` | `list`, `new`, `create`, `detail`, `edit`, `update`, `delete` | `animal_id` debe existir; FK referencial verificada. 422 con mensaje en español si referencia rota. |
| `casas-acogida` | `list`, `new`, `create`, `detail`, `edit`, `update`, `delete` | Campo `capacidad` validado por la service; pasar string no entero produce 422. |
| `acogidas` | `list`, `new`, `create`, `detail`, `edit`, `update`, `close`, `delete` | `close` cambia estado del animal; verificar redirect a `detail` con fecha final actualizada. |
| `voluntarios` | `list`, `new`, `create`, `detail` | Validación `VoluntarioValidationError` ante nombre vacío (422). |
| `adopciones` | `list`, `new`, `create`, `detail`, `edit`, `update`, `delete`, `seguimiento` PATCH | `seguimiento` es el endpoint de la máquina de estados (transiciones válidas e inválidas). |
| `sanidad` | `list`, `new`, `create`, `detail`, `edit`, `update`, `delete` | Catálogo `catalogos_pruebas` debe estar poblado para dropdowns. |
| `salud` | `terapias` (list, new, create, detail, edit, update, delete) y `recomendaciones` (list, create) | `delete` rechaza 409 si hay recomendaciones pendientes. |
| `materiales` | `list`, `new`, `create`, `detail`, `edit`, `update`, `deactivate` | Duplicado de natural-key `(material, tamano, color)` devuelve 409 con mensaje específico. |
| `foster/asignar` | `GET` y `POST` del gate | Bloqueo por especie, admisión directa, admisión con override que requiere `motivo`. |
| `/admin` | redacción de usuarios y desactivación | Sólo `developer`; lector sin sesión es redirigido a `/login`. |

### P1 — Importante (segunda iteración)

| Módulo | Rutas a cubrir | Notas de diseño |
|---|---|---|
| `entradas/batch` | `new`, `POST`, `GET {id}`, `commit`, `cancel` | Cinco filas mínimas; duplicados entre batches devuelven 409. |
| `sanidad/batch` | `new`, `POST` (con `dry_run=true`) | Catálogo debe tener al menos cinco `tipo_actuacion_id` distintos. |
| `materiales/acogidas` | `GET list`, `POST assign`, `POST delete junction` | 422 si la estancia está cerrada o el material inactivo; 409 si la asignación ya existe. |
| `voluntarios/roles` | `roles/add`, `roles/remove` | Verificar que `add` rechaza duplicados. |
| `voluntarios/deactivate` | `deactivate` | Soft-delete; redirige a `list`. |
| `tareas` | `list`, `create`, `detail`, `asignar`, `cerrar` | Redirigen a `list`; verificar 303. |
| `/admin/users` | `POST` crear, `POST .../deactivate` | Validar last-developer guard: no permitir desactivar al único developer. |
| `casas-acogida/overrides` | `GET` listado | Muestra overrides históricos con motivo. |
| `salud/recomendaciones` | `PATCH` marcar completada, `DELETE` soft-delete | Devuelven 303 a la lista. |

### P2 — Deseable (tercera iteración)

| Módulo | Rutas a cubrir | Notas de diseño |
|---|---|---|
| `animals/search` | `GET` JSON con `?q=` | Acepta prefijo de chip, nombre o número de colegiado. |
| `animals/{id}/salud/resumen` | `GET` JSON | Estructura con próximas vacunas, profilaxis pendientes, observaciones recientes. |
| `animals/{id}/foto` | `GET` binario | 404 cuando el animal no tiene foto; `Content-Type: image/jpeg` cuando sí. |
| `/auth/callback` | `GET` con `code` válido e inválido | El callback real requiere Google OAuth; simular con mock. |
| `/admin` listado paginado | `GET` con `?page=` | Sólo si el panel añade paginación en el futuro. |

---

## Plan por fichero nuevo

Todos los tests E2E autenticados comparten la fixture `authenticated_page` ya presente en `tests/e2e/test_admin_authenticated.py`.

Cada fichero declara su propio `import` de esa fixture. Reutiliza el patrón `browser_context.request.get(...)` para mintear la cookie antes del primer `page.goto`.

### Fichero 1 — `tests/e2e/test_animales_crud.py`

**Precondiciones**: sesión activa vía `authenticated_page`. Catálogo `catalogos_pruebas` y `catalogos_origenes` poblados con datos mínimos.

**Casos a cubrir**:

| Caso | Pasos resumidos | Asserts |
|---|---|---|
| Listar animales | `GET /animales` | 200; tabla con los animales existentes |
| Crear animal válido | `GET /animales/new` → rellenar `nombre`, `chip`, `especie=perro`, `sexo=macho`, `fecha_nacimiento` → submit | 303 a `/animales/{id}`; el detalle muestra el chip |
| Crear animal con chip duplicado | Repetir con el mismo `chip` | 422 con mensaje en español |
| Editar animal | Navegar a `edit`, cambiar `nombre`, submit | 303 a `detail`; el nuevo nombre aparece |
| Soft-delete | `POST /animales/{id}/delete` | 303 a `/animales`; el animal ya no aparece en la lista |
| `PATCH /chip` | Enviar payload JSON con `new_chip` y `reason` | 200 con `{ "ok": true }`; el chip nuevo se refleja en `detail` |
| Foto ausente | `GET /animales/{id}/foto` | 404 |
| Búsqueda por chip parcial | `GET /animales/search?q=ABC` | 200 JSON con `results: [...]` |

### Fichero 2 — `tests/e2e/test_entradas_crud.py`

**Precondiciones**: animal preexistente. `voluntario_entrada_id` resuelto a partir de `voluntarios` creado en este set.

**Casos a cubrir**: list, new, create válido, detail, edit, update, delete. Caso 422 con `animal_id` inexistente. Caso 422 con `fecha_entrada` futura.

### Fichero 3 — `tests/e2e/test_entradas_batch.py`

**Casos**: `GET /entradas/batch/new` (cinco filas iniciales); `POST` con cinco filas válidas redirige a `/entradas/batch/{id}`; `GET {id}` muestra el preview con estado por fila; `POST {id}/commit` redirige a `/entradas` con `nuevos` registros; `POST {id}/cancel` elimina el staging. Caso 422 con menos de cinco filas.

### Fichero 4 — `tests/e2e/test_casas_acogida_crud.py`

**Casos**: list con `?especie=gato` filtra; `new` con todos los campos obligatorios; `create` con `capacidad` no entera produce 422 (Pydantic); `edit` y `update`; `delete`; `detail` muestra `capacidad` y observaciones.

### Fichero 5 — `tests/e2e/test_casas_acogida_asignar.py`

**Casos**: `GET /casas-acogida/{id}/asignar` muestra formulario con casa; `POST` con especie no compatible devuelve 422 con la `reason` del gate; `POST` con especie compatible redirige a `/acogidas/new?animal_id=...&casa_acogida_id=...`; `POST` con admisión condicionada y `motivo` vacío devuelve 422; `POST` con `motivo` no vacío redirige con `override_id`; `GET /casas-acogida/{id}/overrides` lista overrides.

### Fichero 6 — `tests/e2e/test_acogidas_crud.py`

**Casos**: list (con y sin `?activas_solo=1`); create a partir de `animal_id` y `casa_acogida_id` válidos; detail muestra duración calculada y estado activo; `POST /acogidas/{id}/close` actualiza `fecha_final`; edit y update; delete. Caso 422 con `casa_acogida_id` inexistente (TOCTOU).

### Fichero 7 — `tests/e2e/test_voluntarios_crud.py`

**Casos**: list, new, create con `Voluntario` obligatorio; detail muestra roles actuales. Caso 422 con `Voluntario` vacío (mensaje de `VoluntarioValidationError`).

### Fichero 8 — `tests/e2e/test_voluntarios_roles.py`

**Casos**: `POST roles/add` añade rol; idempotencia (segundo add devuelve 422 o 409 según contrato); `POST roles/remove` quita rol; `POST .../deactivate` desactiva voluntario y lo retira del listado activo.

### Fichero 9 — `tests/e2e/test_adopciones_crud.py`

**Casos**: list con `?adoptante=` filtra; create con todos los campos obligatorios (`animal_id`, `nombre_adoptante`, `fecha_adopcion`, `tipo_adopcion`); detail muestra seguimiento; edit y update; delete. Caso 422 con `animal_id` inexistente.

### Fichero 10 — `tests/e2e/test_adopciones_seguimiento.py`

**Precondiciones**: adopción creada en estado inicial.

**Casos**: `PATCH /adopciones/{id}/seguimiento` con transición válida (definida en `app/modules/adopciones/domain/state_machine.py`) devuelve 200; transición inválida devuelve 422; doble transición a estado terminal cierra la adopción y bloquea nuevas transiciones.

### Fichero 11 — `tests/e2e/test_sanidad_crud.py`

**Casos**: list con `?animal_id=` filtra; new con `tipo_actuacion_id` del catálogo; create; detail con observaciones; edit, update, delete.

### Fichero 12 — `tests/e2e/test_sanidad_batch.py`

**Casos**: `GET /sanidad/batch/new` muestra cinco filas; `POST` con cinco filas válidas redirige a `/sanidad`; `POST` con `dry_run=true` muestra preview sin INSERT.

### Fichero 13 — `tests/e2e/test_tareas_crud.py`

**Casos**: list con `?responsable_id=` filtra; `POST /tareas` crea tarea manual redirigiendo a `detail`; `POST /tareas/{id}/asignar` asigna responsable; `POST /tareas/{id}/cerrar` cierra la tarea.

### Fichero 14 — `tests/e2e/test_salud_terapias.py`

**Casos**: list con `?animal_id=` filtra; new; create con `animal_id` válido; detail muestra recomendaciones; edit, update; delete con recomendaciones pendientes devuelve 409 con mensaje en español; delete sin recomendaciones redirige a `/terapias`.

### Fichero 15 — `tests/e2e/test_salud_recomendaciones.py`

**Casos**: `GET /terapias/{id}/recomendaciones` lista; `POST` añade recomendación; `PATCH /recomendaciones/{id}` marca como completada; `DELETE /recomendaciones/{id}` soft-delete.

### Fichero 16 — `tests/e2e/test_materiales_crud.py`

**Casos**: list; new; create con `(material, tamano, color)` únicos; create con duplicado devuelve 409 con mensaje específico; detail; edit; update; `POST .../deactivate` soft-delete y redirección a `/materiales`.

### Fichero 17 — `tests/e2e/test_materiales_acogidas_junction.py`

**Casos**: `GET /acogidas/{estancia_id}/materiales` lista materiales asignados; `POST .../materiales` con material activo y estancia abierta asigna y redirige; `POST .../materiales` con material inactivo devuelve 422; `POST .../materiales` con asignación duplicada devuelve 409; `POST .../materiales/{junction_id}/delete` desactiva y refresca la lista.

### Fichero 18 — `tests/e2e/test_cesiones.py`

**Casos**: `GET /cesiones/new` muestra formulario con veinte campos; `POST /cesiones` con `entrada_id` ya usado devuelve 409; `POST` válida redirige a `/entradas/{entrada_id}`.

### Fichero 19 — `tests/e2e/test_admin_panel.py`

**Precondiciones**: sesión `developer`.

**Casos**: `GET /admin` renderiza panel con tabla de usuarios; `POST /admin/users` con email y rol válidos añade fila; `POST /admin/users` con email duplicado re-renderiza con flash de error; `POST /admin/users/{user_id}/deactivate` con otro developer presente desactiva; intento de desactivar al único developer redirige con flash «último developer». Verificar que sin sesión `GET /admin` redirige a `/login`.

### Fichero 20 — `tests/e2e/test_rbac_writer_vs_developer.py`

**Precondiciones**: dos sesiones, una con `developer` (mock), otra con `reader`/`writer` mediante seed en `usuarios_autorizados` (fuera del alcance del mock — ver bloqueadores).

**Casos**: el writer puede `POST` formularios de creación; el reader recibe 403 al intentar `POST`; el reader sí ve listados (200). Mantener este fichero mínimo como regression del gate RBAC; expandir cuando los roles estén disponibles en CI.

### Fichero 21 — `tests/e2e/test_csrf_enforcement.py`

**Casos**: `POST` sin `csrf_token` es rechazado por `CsrfMiddleware` (403 o 422 según contrato); `POST` con token incorrecto también; `POST` con token válido fluye. Aplicar al menos a `/animales`, `/entradas`, `/sanidad`, `/adopciones`, `/materiales`.

### Fichero 22 — `tests/e2e/test_error_pages_and_redirects.py`

**Casos**: `GET /animales/{id-que-no-existe}` devuelve 404; `GET /animales/{id}/edit` sin permiso writer devuelve 403; navegación entre módulos no rompe la sesión; cierre y reapertura de navegador preserva la cookie mientras no expire.

---

## Convenciones para los nuevos tests

| Aspecto | Convención |
|---|---|
| Fixture de autenticación | Copiar `authenticated_page` de `tests/e2e/test_admin_authenticated.py` al `conftest.py` para reutilización. Eliminar la duplicación local una vez el primer fichero nuevo la necesite. |
| `base_url` | Reutilizar la fixture existente; nunca hardcodear URL. |
| Selectores | Preferir `page.get_by_role(...)` y `page.get_by_label(...)` cuando el template expone `<label for>`. Para inputs sin label visible, usar `input[name="..."]` con el `name` declarado en el `Form()` de cada módulo. |
| CSRF | Los formularios incluyen `<input type="hidden" name="csrf_token" value="{{ csrf_token }}">`. El test debe leer el token del DOM con `page.locator('input[name="csrf_token"]').get_attribute('value')` y reenviarlo en el `submit` siguiente. |
| Datos de prueba | Sembrar vía la API (POST directos a `/entradas` o `/animales`) usando la sesión autenticada; evitar SQL directo desde los tests E2E. |
| Aislamiento | Cada test debe partir de un estado limpio. Crear los animales y entradas necesarios al inicio del test, no depender de filas preexistentes. |
| Skip condicional | Aplicar `_skip_if_oauth_not_configured` cuando el endpoint devuelva 503 por falta de secretos. Para los tests autenticados, aplicar skip si `APAP_E2E_AUTH_SECRET` está vacío. |
| Server URL | El test runner asume un servidor levantado en `BASE_URL`. Documentar en `CONTRIBUTING.md` cómo arrancarlo con `make run` antes de `pytest tests/e2e/`. |

---

## Estimación

| Categoría | Ficheros nuevos | Tests estimados |
|---|---|---|
| P0 — CRUD por módulo | 11 | ~80 |
| P1 — Batch, junction, RBAC, admin | 7 | ~30 |
| P2 — Search, JSON, errores | 4 | ~15 |
| **Total** | **22** | **~125** |

Supuestos:

- Cada CRUD aporta siete tests promedio (uno por método).
- Las pruebas de gate y junction añaden dos a cuatro tests adicionales.
- Las pruebas transversales (CSRF, RBAC, errores) son cortas y comparten fixtures.

---

## Bloqueadores conocidos

| Bloqueador | Impacto | Mitigación propuesta |
|---|---|---|
| El mock `GET /e2e/login` sólo emite cookies con rol `developer` | Los gates de `writer`, `key_user` y `reader` no son ejercitables con el mock. `test_rbac_writer_vs_developer.py` queda como regression parcial. | Sembrar `usuarios_autorizados` desde la capa de tests con rol `writer` y `reader`; el mock debería aceptar `?rol=` como parámetro (issue de seguimiento). |
| La base de datos de desarrollo (InsForge) puede no estar disponible en CI | Los tests autenticados fallarán en datos con 500 si InsForge está caído. | El mock ya pre-puebla la auth cache, pero las queries SQL reales siguen requiriendo InsForge. Documentar en el README del workflow E2E la dependencia. |
| `playwright install chromium` añade ~150 MB a la imagen CI | El job E2E ya está documentado como opcional. | Mantener `APAP_E2E_SKIP=1` por defecto hasta que se decida levantar el job. |
| El campo `chip` en `animales` exige unicidad | El orden de los tests CRUD puede chocar si comparten fixtures. | Sembrar el `chip` con `uuid.uuid4().hex[:10]` por test. |

---

## Roadmap de implementación

1. Subir la fixture `authenticated_page` al `conftest.py` común para eliminar duplicación.
2. Implementar los once ficheros P0 (CRUD) en orden de dependencia: `voluntarios` → `animals` → `entradas` → `casas-acogida` → `acogidas` → `adopciones` → `sanidad` → `salud/terapias` → `materiales` → `casas-acogida/asignar` → `adopciones/seguimiento`.
3. Implementar los siete ficheros P1, priorizando `entradas/batch`, `sanidad/batch` y `materiales/acogidas junction` por densidad de lógica.
4. Implementar los cuatro ficheros P2 como smoke tests ligeros.
5. Activar el workflow CI E2E con `playwright install chromium` y los secretos `APAP_E2E_AUTH_SECRET` y `APAP_TEST_POSTGRES_DSN` ya existentes.

---

## Referencias

- `tests/e2e/conftest.py` — fixtures compartidas y auto-skip.
- `tests/e2e/test_admin_authenticated.py` — plantilla de la fixture `authenticated_page`.
- `app/core/e2e_auth.py` — contrato del mock OAuth (cabecera `X-E2E-Secret`, parámetro `email`, JSON de respuesta).
- `app/routes_registry.py` — orden de montaje de routers que explica la precedencia de rutas dinámicas.
- `docs/audits/e2e-coverage-2026-Q3.md` — auditoría previa con el inventario OAuth-bloqueado.
- `app/modules/*/routes.py` — superficie HTTP auditada para este plan.
