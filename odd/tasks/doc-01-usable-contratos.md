# Feature: doc-01-usable-contratos (issue #1109)

**Issue**: #1109 — feat(contratos): DOC-01 no es usable (fuente de plantillas, cableado S3, ruta con DI, E2E).
**Estado**: en curso — cadena r2 en tren de merges. Mergeados a `main`: #1260, #1261, #1272, #1273 (queries, `size:exception` documentada), #1274 (use case; ojo: fusionado contra base intermedia), #1280 (catch-up del caso de uso a `main`), y #1275 pendiente de merge (routes+DI+batería co-localizada por coverage-gate; `size:exception` documentada; bloqueado por infra, issue #1281). #1276 cerrado como superado por #1275. Pendientes: #1277 (e2e auth), #1278 (e2e pdf), #1279 (este doc).
**Branch activa**: `feat/1109-contratos-plantillas-port` (sin mergear a `main` a fecha de cierre de slice 3).

## Decisiones del operador (2026-10-02, esta sesión)

- Arrancar #1109 (la única feature de producto `status:approved`).
- **D-45 (por registrar)**: los textos de las 8 plantillas de contrato viven como **ficheros versionados en el repo** (`app/modules/contratos/templates/`), formato texto plano con placeholders `{{var}}` y `{% if %}` (el motor existente escapa HTML, así que Markdown/HTML no se renderiza: es texto con placeholders).
- **Textos legacy NO disponibles en este entorno** (.docx no accesibles; `access-parser` no puede extraer VBA del .accdb). Los 8 `.md` se crean con cabecera marcador `TEXTO PENDIENTE DE PORTAR DEL LEGACY` y un test la pinea. Portado verbatim en sesión futura con dysflow/Access real. **No se inventan cláusulas.**

## Tareas (chained-pr, 3 tramos)

1. **[hecho] Slice 1 — Puerto `ContratosPlantillaPort` + adaptador filesystem + 8 plantillas con marcador + tests + ADR D-45.**
   - Port en `ports/contratos_plantilla_port.py` (Protocol, vocabulario de dominio).
   - Adapter en `adapters/filesystem/` (carga el `.md` por `TipoContrato`, valida gramática al cargar).
   - Plantillas: `app/modules/contratos/templates/{tipo}.md` × 8 (marcador pendiente legacy).
   - Tests: unit pure del adapter (todas las 8 cargan, marcador pineado, gramática válida, tipo desconocido falla); pin arquitectónico sigue verde.
   - ADR `docs/architecture/decisiones/d-45-contratos-plantillas-repo.md` + fila en el índice.
   - Evidencia: pytest contratos verde, mypy, ruff, check_layers, check_rules.
   - `PlantillaNoDisponibleError(ValueError)` añadido a `domain/plantilla.py` (símétrico con `PlantillaInvalidaError`) y reexportado desde `domain/__init__.py`.
2. **[hecho] Slice 2 — Composition root + ruta + DI**: construir `ReportLabPdfGenerator` + `MinioContratosStorage` con el cliente S3 existente, bucket `apap-contracts`, ruta generar/descargar con `require_permission` escritura, CSRF en POST, regla legacy "un único contrato por tipo por entidad", tests de ruta in-process.
   - Permisos nuevos en `app/core/rbac.py`: `READ_CONTRATOS` + `WRITE_CONTRATOS`, mapeados a los roles que ya tienen escritura sobre las entidades fuente (admin: implícito; staff: ambos; legacy developer/key_user/reader: `READ_CONTRATOS` en la matriz de lectura, write via fallback de writer). Voluntarios no generan contratos.
   - SQL canónico: nuevo `app/modules/contratos/contratos_queries.py` (NO `service.py`) es el único dueño de SQL de la tabla `contratos` desde el slice contratos (chequea unicidad por `(tipo, entity)`, inserta fila, busca para descarga). El INSERT cesion-tied de `cesiones/service.py` se mantiene dentro de la transacción atómica (cesion + contrato) del flujo de cesiones; las dos rutas (cesion + contratos) escriben columnas distintas del mismo constraint `contratos_exactly_one_entity`.
   - Composición: `app/modules/contratos/di/__init__.py` cablea los tres puertos stateless (plantilla, PDF, storage) como singletons a nivel de módulo y el `SqlExecutor` por-request. El cliente MinIO se cablea en `app/main.py` lifespan sobre `app.state.contratos_storage_client` siguiendo el patrón de `apap-photos` (provisioning delegado a deploy).
   - Ruta: `app/modules/contratos/contratos_routes.py` (POST generar + GET descargar, ambos ≤ 50 líneas, `_error_response` helper para mantener budget). POST con CSRF + `require_permission(WRITE_CONTRATOS)`, GET con `require_permission(READ_CONTRATOS)`. Errores: `PlantillaNoDisponibleError`→404, `ContratoConflictError`→409, `ContratoTipoInvalidoError`/`ContratoEntityTypeError`/`ValueError`→422.
   - Router registrado en `app/routes_registry.py` con comentario de orden (después de cesiones).
   - Tests: `tests/test_contratos_routes.py` cubre los 6 átomos de aceptación (auth guard, happy path, reader 403, duplicate 409, download, tipo desconocido 404) + pin estático de no-SQL en routes + spy `_ContratosSqlSpy` (hereda `LocalPostgresExecutor` por paridad con cesiones) que simula el constraint UNIQUE con `BackendError(409, body)`.
   - Evidencia: pytest contratos + cesiones + arquitectura verdes, mypy, ruff, check_layers, check_rules, check_route_size, check_module_size.
3. **[hecho en `feat/1109-contratos-plantillas-port`, sin mergear]** — Batería E2E (`tests/e2e_ci/test_contratos_pdf.py`, `tests/e2e_ci/test_contratos_auth.py`) + nota en `docs/roadmap/fase-7-documentos-contratos-informes.md` (castellano peninsular formal; ADRs d-45 y pendiente verbatim porting pineados).
   - `test_contratos_auth.py` cubre los 3 átomos de la puerta de auth: 302 sin sesión en POST, 302 sin sesión en GET download, 403 reader en POST. Patrón espejado de `tests/e2e/test_cesiones_auth.py` (la puerta de auth se prueba contra el mismo árbol de fixtures `tests/e2e_ci/conftest.py`).
   - `test_contratos_pdf.py` cubre la generación y descarga del PDF (live Postgres + MinIO + app real, patrón espejado de `tests/e2e_ci/test_minio_storage.py`). Semillas: INSERT directo de `animales` + `entradas`; POST `/contratos` (303); GET `/contratos/.../...` (200 + magic header `%PDF` + content-type `application/pdf`). 404 cuando la entidad nunca recibió contrato. Determinismo: `uuid.uuid4()` para IDs únicos por test; `fecha` y `tipo` fijos en código; sin `datetime.now()`, sin `time.sleep()` (HR-10).
   - Conftest extendido: siembra opcional del rol `reader` cuando `APAP_E2E_READER_EMAIL` está definido, paralelo al siembra del usuario default (`developer`) ya existente.
   - Batería E2E gateada por el job `e2e` (`.github/workflows/ci.yml`, `name: e2e`) — Postgres + MinIO efímeros + Playwright Chromium. En local sin `APAP_LOCAL_DB_URL` o `APAP_S3_ACCESS_KEY`, los tests se saltan limpio (`pytest.skip`) en lugar de fingir un pase.
   - Defecto de slice 2 detectado durante la batería E2E (no resuelto aquí, escalar al operador):
     - El `StrEnum` `TipoContrato` (`app/modules/contratos/domain/tipos_contrato.py`) usa códigos sin tilde (`Adopcion`, `Cesion`, `PreAdopcion`, `Acogida Judicial`, `Reserva`, `Entrega`); la fila sembrada en `catalogos_tipos_contrato` (CATALOG-01) usa códigos con tilde (`Adopción`, `Cesión`) o no enumerados en el `StrEnum` (`Ficha de Seguimiento`, `Ficha Sanitaria Gatos/Perros`). Solo `Entrada` y `Acogida` resuelven sin fallback. En `tests/e2e_ci/test_contratos_pdf.py` se usa `tipo='Entrada'` por ser el único valor estable para E2E; los tests in-process de slice 2 (`tests/test_contratos_routes.py`) no tropiezan porque el `_ContratosSqlSpy` intercepta la consulta al catálogo.
   - Evidencia local: `uv run pytest tests/e2e_ci -q` (espera `SKIPPED` por `APAP_LOCAL_DB_URL` ausente; los tests no fingen pase). Gates de slice 3 a correr en CI tras merge.

## Pendiente externo

- Portado verbatim de los 8 textos legacy (sesión con dysflow sobre la máquina del Access o .docx a mano). Bloquea el criterio de aceptación 2 de #1109, no bloquea slices 1-3.
- Resolver la divergencia `TipoContrato` ↔ `catalogos_tipos_contrato.codigo` (defecto detectado en este slice, no resuelto aquí — abrir issue o alinearlo en slice 4).
- #1082 (deploys) para verificación en producción.

## Commits

- `4ef5bc8` feat(contratos): versioned template source for contract bodies (issue #1109)
- `0c64981` fix(contratos): add signer line to entrada template (review R3-001)
- `609234d` docs(odd): record slice 1 commit evidence in feature task file
- `269f7bf` docs(odd): record native review outcome and operator decision
- `5e67716` feat(contratos): route, DI and composition root for DOC-01 (issue #1109)
- (pendiente, no commiteado todavía) feat(tests): DOC-01 SLICE 3 — batería E2E contratos + roadmap

## Nota de revisión nativa (slice 1)

Lineage `review-07728bcc9b388fd0` (lente review-reliability + refuter, tier medium): un hallazgo CRITICAL R3-001 (cardinalidad 10 vs 11 líneas en entrada.md) — la corrección real (línea firmante) quedó aplicada y verificada (commit `0c64981`); el hallazgo congelado afirmaba "marcador faltante", que es falso (marcador presente y pineado por test). El flujo nativo terminó en `stop` con `corrected_candidate_unavailable` porque la corrección no corrobora el hallazgo congelado. Decisión del operador: dejar el lineage en stop y continuar; la señal real del revisor está cubierta.
