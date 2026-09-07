[← Back to README](../../README.md)

# pii-live-migration-2026-Q3.md

This audit documents the scope, methodology, findings, and verdict for the audit listed in the title. Esta auditoría documenta el alcance, la metodología, los hallazgos y el veredicto del estudio PII del live migration (PR4b) ejecutado durante 2026 Q3, que cubre la superficie PII de la migración M1 forward, la ruta autenticada de display de fotos, los invariantes de redacción en storage y la lista de redacción de `log_safe`, con extensiones posteriores en PR5 (M1 collision routing) y PR6 (M2 reverse path + round-trip).

| Sección | Descripción |
|---|---|
| [Scope](#scope) | Columnas PII, rutas de display, storage y lista de redacción. |
| [Methodology](#methodology) | Procedimiento aplicado y átomos que pinean los invariantes. |
| [Findings](#findings) | Severidad, título, forma y detalle de cada hallazgo. |
| [Verdict](#verdict-pr4b) | Estado final del cierre PII de M1 y M2. |
| [References](#references) | Tests, runbook y operator acknowledgement. |

## Scope

| Item | Value |
|---|---|
| Audit slice | Live migration PII surface (M1 forward + M2 reverse) |
| PRs cubiertos | PR4b (forward), PR5 (collision routing), PR6 (reverse + round-trip) |
| Out of scope | M2 reverse path (PR6/PR7), production release tags, public galleries, anonymization, encryption-at-rest más allá de los defaults de LocalBackend |

### Columnas PII en alcance

| Columna | Origen (legacy) | Columna web | web_only_strategy | Forward path |
|---|---|---|---|---|
| `email` | `TbVoluntariosParaAutorrellenables.Email` | `voluntarios.email` | mapped 1:1 | forward + reverse |
| `tel1` | `TbVoluntariosParaAutorrellenables.Tel1` | `voluntarios.tel1` | mapped 1:1 | forward + reverse |
| `tel2` | `TbVoluntariosParaAutorrellenables.Tel2` | `voluntarios.tel2` | mapped 1:1 | forward + reverse |
| `dni` | (no legacy column — verificado vía Dysflow `get_schema` el 2026-07-11) | `voluntarios.dni` | `preserve` (web-only shadow; round-trip) | never forward-migrated; preserved on web-side; reverse-path collision is recorded as `needs_review` |

> **Por qué no hay columna `DNI` en legacy.** `TbVoluntariosParaAutorrellenables` devuelve exactamente cuatro columnas (`Voluntario, Tel1, Tel2, Email`, todas `type=10 text size=255`). Cualquier afirmación futura de que DNI existe en esta tabla legacy must re-verificarse vía la misma herramienta Dysflow `get_schema`. El mapping `migration/mappings/voluntario.yaml` ya codifica esta realidad (`DNI` tiene `legacy_column: null`, `web_only_strategy: preserve`).

### Rutas de display en alcance (PII puede accederse vía estas)

| Ruta | Auth requerida | Sin sesión |
|---|---|---|
| `GET /voluntarios` | sí | 302 `/login` |
| `GET /voluntarios/{id}` | sí | 302 `/login` |
| `GET /animales` | sí | 302 `/login` |
| `GET /animales/{animal_id}` (UUID) | sí | 302 `/login` |
| `GET /animales/{animal_id}/foto` (UUID) | sí | 302 `/login` |
| `GET /entradas` | sí | 302 `/login` |
| `GET /login` | no | 200 |

`PUBLIC_PATHS` en `app/main.py:148` es el set cerrado de endpoints intencionalmente no autenticados: `{/healthz, /login, /auth/google, /auth/callback, /logout}` (5 entradas). Solo `/login` expone contenido de aplicación; los otros cuatro son superficies protocolares/operativas (liveness probe, OAuth flow start, OAuth callback, session clear) que por diseño no leak PII.

### Storage en alcance

- `apap-photos` private bucket (`isPublic=false`); invariante de pre-flight es `isPublic == False` y el apply aborta en `True` o ausente.
- Las object keys son client-derived como `<sha256>.<ext>` (SHA-256 de los bytes + extensión detectada). El server puede renombrar en colisión; la key canónica es el campo `key` devuelto por el upload-strategy.
- `animales.nombrefoto` almacena la key **devuelta** (no el filename legacy, no la key propuesta si el server renombró).
- Sentinel `__missing__` se fija cuando la foto fuente falta, está corrupta o no soportada; la ruta sirve un placeholder PNG 1x1 sin storage I/O.

### Lista de redacción (`app/core/logging.py::REDACTED_FIELDS`)

Tras PR4b la lista cerrada tiene 15 entradas: `email, session_token, jwt, oauth_code, pkce_verifier, csrf_token, pkce_challenge, authorization, cookie, referer, ip_address, x_forwarded_for, dni, tel1, tel2`. La comparación es case-insensitive y trata `-` y `_` como equivalentes.

## Methodology

Seis invariantes se pinean por átomos automatizados. Cada átomo es una fixture que pre-carga el fake relevante, ejercita el contrato y afirma el post-state con un valor concreto (no absence-of-error).

1. **Shape de la lista de redacción** — `tests/test_logging.py` + `tests/test_log_safe_redaction.py` (15 átomos tras expansión de parametrización). La lista tiene exactamente 15 entradas; cada nuevo campo PII (`dni`, `tel1`, `tel2`) está presente; las variantes mixed-case (`DNI`, `Tel1`, `TEL2`) se redactan; los nombres descriptivos que meramente contienen un substring redactado (`dni_lookup_table`, `telefono_secundario`) pasan sin cambio.
2. **Invariante de autorización** — `tests/test_animals_foto_route.py::TestFotoRouteAuthorizationInvariant` pinea que un request anónimo redirige a `/login` antes de cualquier llamada a DB o storage. Sin queries SQL, sin llamadas a storage.
3. **Sin leak de presigned-URL** — `tests/test_animals_foto_route.py::TestFotoRouteDoesNotLeakPresignedUrl` pinea que ninguna cabecera o body de la respuesta contiene la URL de storage o cualquier token presigned, incluso cuando la superficie de storage levantó con esa URL en su body de error.
4. **Fail-closed en cada categoría de error de storage-stream** — `tests/migration/test_storage_methods.py` parametriza 401, 403, 404, 405, 500 sobre el upload strategy; `download_object_stream` lanza `BackendError` en 401/404/5xx y `httpx.TimeoutException` en network timeout. La capa de ruta en `tests/test_animals_foto_route.py::TestFotoRouteMidStreamFailClosed` cubre cuatro paths de emisión de placeholder: streamed-GET 5xx (`test_foto_route_placeholder_when_streamed_get_5xx_on_first_chunk`), network drop mid-iteration (`test_foto_route_placeholder_when_stream_mid_iteration_network_error`), streamed-GET succeeds for headers pero falla en first-iteration (`test_foto_route_placeholder_when_stream_fails_on_first_iteration`), y per-chunk read timeout (`test_foto_route_placeholder_on_per_chunk_timeout`). El photo service consume el generador de storage eagermente para que un `PhotoStreamError` mid-stream siempre se vuelva el PNG placeholder — nunca un 5xx. El wrapping a nivel de servicio está pineado por `tests/test_animals_foto_route.py::TestFotoServiceMidStreamWrapping`. **PR4b 4R WARN-3**: excepciones inesperadas en el SELECT de animales (`animals_service.get_animal_by_id`) TAMBIÉN fallan closed al placeholder, por consistencia con el contrato de storage-stream. `tests/test_animals_foto_route.py::TestFotoRouteSqlLookupFailClosed` pinea tanto `BackendError` (con sabor transport) como un `RuntimeError` no-LocalBackend (con sabor invariant-violation). El error se registra vía `log_safe("animal_foto.sql_lookup_failed", reason=...)` para que el operador lo siga viendo en el audit stream. Un animal genuinamente ausente (el service devuelve `None`) sigue surfacing como 404 porque la ausencia es una señal de dominio, no un fallo de transporte.
5. **Upload idempotente** — `tests/migration/test_storage_methods.py::test_upload_object_reuses_existing_key_via_client_derived_filename` afirma que los mismos bytes subidos dos veces llevan el mismo client-side filename para que el dedup del lado server pueda dispararse.
6. **Sin `logger.*` raw / `print(...)` en `app/core/local_backend.py`** — `tests/migration/test_storage_methods.py::test_storage_methods_never_log_secrets_urls_or_paths` usa el AST detector de `scripts/check_rules.py` (el mismo detector que corre en CI) para pinear la ausencia de patrones de logging prohibidos en la superficie de storage de producción.

Además, el runbook operator `docs/runbooks/live-migration-apply.md` carga el workflow operator canónico; `tests/test_runbook_links.py` pinea que cada referencia a runbook operator-facing resuelve a un fichero authored con los headings de AGENTS.md §13 (`## When to trigger`, `## Pre-deploy checklist`, `## Deploy steps`, `## Verification`, `## Rollback`).

### Re-audit de layering del issue #233 (2026-07-20)

El árbol fail-closed vive en `adapters/local-backend/animals_local_backend_photo.py`. La ruta solo aplica auth, traduce 404 y construye el streaming response. Los tests de ruta y adaptador verifican el boundary preservado.

## Findings

| Severity | Title | Form | Details |
|---|---|---|---|
| MEDIUM | El sentinel placeholder es un PNG 1x1 transparente estático; los usuarios no ven ningún hint de "imagen rota" | deferred | `animals_local_backend_photo.py::PLACEHOLDER_PHOTO_PNG`; `animals_local_backend_photo.py::PHOTO_SENTINEL_KEY`. Mejora de UX, no un defecto de seguridad. Aceptado (fuera del alcance de PR4b). |
| MEDIUM | `delete_object` 404 devuelve `None` (idempotente) — si el operador loguea el valor de retorno no ve señal de "ya ausente" | deferred | `tests/migration/test_storage_methods.py::test_delete_object_404_is_idempotent_noop`. Sin leak de PII ni de secretos; solo operator UX. Aceptado (fuera del alcance de PR4b). |
| LOW | El resolver cae a `application/octet-stream` para extensiones desconocidas; los navegadores descargarán en vez de inline | deferred | `animals_local_backend_photo.py::_content_type`. Default defensivo, sin impacto de seguridad. Aceptado. |
| LOW | `voluntarios.dni` es web-only shadow (verificado vía Dysflow `get_schema` 2026-07-11: cero columna DNI en `TbVoluntariosParaAutorrellenables`) | deferred | Forward legacy apply must dejar `dni=NULL`; las colisiones solo surgen de manual web entry (UNIQUE constraint) o reverse-path (no hay columna legacy que recibir). `migration/mappings/voluntario.yaml` (`DNI: legacy_column: null`); `tests/test_log_safe_redaction.py::test_log_safe_redacts_each_new_pii_field_value[dni]`; la fila `dni` en la tabla Scope de arriba. Por diseño — preserva la fidelidad P1 al schema legacy verificado. |
| LOW | El audit doc se renderizó en inglés por default del artifact; el registro preferido del proyecto para docs de operador es castellano de España | deferred | El default (inglés) se eligió porque la regla de artifact-language (technical artifacts default to English a menos que el proyecto solicite explícitamente otro idioma) toma precedencia sobre la preferencia de operator-doc para este audit. `docs/audits/pii-live-migration-2026-Q3.md` (este fichero). Aceptado — el operador puede solicitar un render en castellano en un follow-up. |

## Verdict (PR4b)

PASS: cada control PII de PR4b está pineado por un átomo automatizado. La gate del milestone M1 acepta el contrato PII sobre la base de:

- La lista cerrada de redacción (15 entradas) está verificada end-to-end por átomos parametrizados en `tests/test_log_safe_redaction.py` (**15 átomos** tras parametrización: 1 invariante de shape de lista + 3 presencia-por-campo + 3 redacción-por-campo + 6 variantes mixed-case + 1 no-leak del formatted message + 1 passthrough de nombres descriptivos).
- La ruta `GET /animales/{animal_id}/foto` está verificada por `tests/test_animals_foto_route.py` (**18 átomos** repartidos en 5 clases: `TestFotoRouteAuthAndRouting` 6, `TestFotoRouteDoesNotLeakPresignedUrl` 1, `TestFotoRouteIsolatedService` 1, `TestFotoRouteAuthorizationInvariant` 1, `TestFotoRouteMidStreamFailClosed` 4, `TestFotoRouteSqlLookupFailClosed` 2, `TestFotoServiceMidStreamWrapping` 3).
- Los métodos de storage de producción en `LocalBackendClient` están verificados por `tests/migration/test_storage_methods.py` (**30 átomos**: happy/sad/edge para upload_object (4 + 6 fail-closed parametrizados + transfer/confirm/network), download_object_stream (7 + 2 per-chunk timeout), delete_object (3); unsafe-bucket pre-network × 3; idempotent re-upload; bearer auth sobre la strategy request; AST detector pinea la ausencia de patrones de logging prohibidos).
- El path operator de migración está documentado en `docs/runbooks/live-migration-apply.md` con los headings de AGENTS.md §13 y la constante `MIGRATION_RUNBOOK_REF` surfacea este path canónico en cada línea de typed-exception. Las secciones específicas de PR4b (photo display + storage) extienden ese runbook sobre las secciones existentes de apply / pre-flight / rollback / escalation.

### Índice de evidencia de aceptación

| Invariante | Fichero de átomos | Átomos |
|---|---|---|
| `REDACTED_FIELDS` tiene exactamente 15 entradas | `tests/test_log_safe_redaction.py` | 1 |
| Cada nuevo campo PII está en la lista cerrada | `tests/test_log_safe_redaction.py` | 3 |
| `log_safe` redacta cada nuevo valor de campo | `tests/test_log_safe_redaction.py` | 3 |
| Variantes mixed-case se redactan | `tests/test_log_safe_redaction.py` | 6 |
| PII nunca leak via el formatted message | `tests/test_log_safe_redaction.py` | 1 |
| Nombres descriptivos pasan sin cambio | `tests/test_log_safe_redaction.py` | 1 |
| Métodos de storage happy/sad/edge | `tests/migration/test_storage_methods.py` | 30 |
| Per-chunk read timeout pinea `connect=5/read=10/...` | `tests/migration/test_storage_methods.py` | 1 |
| Stream stalled surfacea `httpx.TimeoutException` | `tests/migration/test_storage_methods.py` | 1 |
| Auth gate redirige anónimo a `/login` | `tests/test_animals_foto_route.py` | 2 |
| Animal-not-found devuelve 404 | `tests/test_animals_foto_route.py` | 1 |
| Ruta streamea bytes para keys reales | `tests/test_animals_foto_route.py` | 1 |
| Sentinel + null → placeholder, sin I/O | `tests/test_animals_foto_route.py` | 2 |
| Storage error → placeholder (fail-closed) | `tests/test_animals_foto_route.py` | 1 |
| Mid-stream error → placeholder (CRIT-1, 4R) | `tests/test_animals_foto_route.py` | 4 |
| SQL lookup error → placeholder (WARN-3, 4R) | `tests/test_animals_foto_route.py` | 2 |
| `stream_animal_photo` envuelve errores mid-stream | `tests/test_animals_foto_route.py` | 3 |
| Sin leak de presigned URL | `tests/test_animals_foto_route.py` | 1 |
| Service isolation (sin photo/bucket SQL) | `tests/test_animals_foto_route.py` | 1 |
| Estructura del audit doc (Scope / Methodology / ...) | `tests/test_pii_audit_doc.py` | 7 |
| Referencias de runbook resuelven a ficheros authored | `tests/test_runbook_links.py` | 12 |

## PR5 Additions (2026-07-15)

PR5 (`feat/migration-pr5-pii-controls`, PR #196) re-escope el contrato de colisión M1 y añade cinco nuevos controles PII encima de la superficie de PR4b. Esta sección enumera los nuevos invariantes, los nuevos tests y reconfirma el verdict.

### Nuevos invariantes

| Invariante | Superficie | Dónde vive |
|---|---|---|
| Counter wiring por tabla con DI seam | `apply_legacy_to_web(dni_collision_counter: DniCollisionCounter \| None = None)` expone el counter para el PR6 reverse applier; el forward applier nunca lo bumpa (legacy no tiene DNI). La key operator-facing se renombró de `dni_collisions` a `preserve_advances` (issue #217) para reflejar con precisión que trackea avances de preserve-column, no colisiones reales. | `migration/apply.py` signature; `migration/dni_collision.py::DniCollisionCounter`; `migration/reverse_apply/orchestrator.py` escribe `MigrationReport.collisions[<table>]["preserve_advances"]`; `tests/migration/test_dni_collision.py::test_forward_legacy_produces_zero_dni_collisions` pinea el contrato zero-bump; `tests/migration/test_dni_collision_counting.py` (nuevo) pinea el rename. |
| `--filter-direction {legacy-to-web, web-to-legacy, both}` CLI flag | Por defecto `"both"` para que los callers de PR4 vean el mismo listado combinado; PR5 añade el path de narrowing. | `migration/cli.py::build_parser` + `migration/shadow_state.py::list_needs_review(origin_direction=...)`. |
| `PUBLIC_PATHS` 5-entry shape pineada | Exactamente `{/healthz, /login, /auth/google, /auth/callback, /logout}`; ninguna ruta PII está en el set. | `app/main.py:148`; `tests/test_public_paths.py::EXPECTED_PUBLIC_PATHS`. |
| `_is_pii_web_column` / `_mask_pii_value` CLI helpers | Aplican la comparación de la lista cerrada contra `web_column` para mantener el stdout operator libre de PII raw. | `migration/cli.py`; consumidos por ambos formatters. |
| 5-ruta 302-to-`/login` parametrización | Cada ruta PII-displaying (`/voluntarios`, `/voluntarios/{id}`, `/animales`, `/animales/{id}/foto`, `/entradas`) devuelve 302 a `/login` sin sesión. | `tests/test_public_paths.py::PII_ROUTES_PARAMETRIZE`; la capa de ruta en `app/modules/*/routes.py`. |
| `origin_direction` stamp en filas de `list_needs_review` | Cada fila listada lleva la dirección del producer para que el dashboard operator pueda rutear por scope de migración. | `migration/shadow_state.py::list_needs_review` fija `row["origin_direction"] = "legacy-to-web"` por defecto; el PR6 reverse applier empezará a estampar `"web-to-legacy"`. |
| `record_dni_collision(direction=...)` persiste `origin_direction` | El kwarg `direction` se persiste verbatim en la shadow row (la columna `origin_direction` carga un CHECK de tres valores cerrados: `legacy-to-web`, `web-to-legacy`, `web-only`). | `migration/dni_collision.py::record_dni_collision`; `migration/shadow_state.py::ShadowStateRepository.upsert(origin_direction=...)`. |
| `legacy_pk` / `web_pk` PII masking en CLI output | Un nuevo helper `_looks_like_pii(value)` matchea regexes de DNI / email / phone y enmascara el valor a `[REDACTED]`; los UUIDs y NCHIPs no matchean y pasan sin cambio. | `migration/cli.py::_PII_VALUE_PATTERNS` + `_looks_like_pii`; consumidos por `_format_row_for_check_only` y `_format_row_for_interactive`. |
| `derived_value` PII masking en CLI output | Misma comparación de lista cerrada que `preserved_value`: cuando `web_column` está en `REDACTED_FIELDS`, `derived_value` se enmascara a `[REDACTED]`. | `migration/cli.py` formatters; `tests/migration/test_pii_redaction.py::test_cli_reconcile_check_only_output_has_no_raw_pii` pinea el contrato. |

### Nuevos tests (29 átomos + 3 átomos CLI)

| Suite | Átomos | Cobertura |
|---|---|---|
| `tests/migration/test_pii_redaction.py` | 10 | Redacción `log_safe` sobre el payload `sync.applied` (parametrizado sobre 4 campos PII); shadow `preserved_value` masking; `MigrationReport.to_json()` no-PII regex; CLI stdout no-PII (incluyendo el nuevo `derived_value` masking); redaction-list-covers-all-PII (parametrizado sobre la lista cerrada completa); synthetic-payload-emits-redacted-payload; collision-marker-in-log-payload. |
| `tests/migration/test_dni_collision.py` | 9 | Forward-zero-collision (cablea el DI seam); web-only shadow routing (afirma `origin_direction="web-only"`); reverse-path counter increment (afirma `origin_direction="web-to-legacy"`); interactive CLI resolution; helper invariants (NOW default, first-wins-does-not-overwrite); counter initial state; CLI parser `--filter-direction` surface (default `"both"`). |
| `tests/test_public_paths.py` | 10 | `PUBLIC_PATHS` 5-entry shape invariant; `_is_public_path` recognition; no-PII-route-in-PUBLIC_PATHS; parametrizado 302-to-`/login` sobre 5 rutas PII; `/healthz` y `/login` happy-path sanity. |
| `tests/migration/test_cli.py` | 3 nuevos átomos | `--filter-direction` default (`both`); `--filter-direction legacy-to-web` narrowing; `--filter-direction web-to-legacy` empty-listing en PR5. |

### Verdict (re-confirmado, PR5)

PASS para el M1 forward path. El helper de collision-routing (`migration/dni_collision.py::record_dni_collision`) está completamente unit-tested (9 átomos cubriendo ambos scopes, el counter increment y los invariantes del helper) pero no está invocado por el forward applier — legacy `TbVoluntariosParaAutorrellenables` no tiene columna `DNI` (Dysflow-verified 2026-07-11). El DI seam `apply_legacy_to_web(dni_collision_counter=...)` está cableado hoy para que el PR6 reverse applier pueda invocar el helper en colisiones `web-to-legacy`; el seam está ejercido por el átomo zero-bump en `tests/migration/test_dni_collision.py`.

### PR6 Additions (2026-07-18, reverse apply + round-trip)

PR6 (`feat/live-migration-reverse-apply`) envía el path simétrico `apply_web_to_legacy` y añade cinco invariantes de round-trip encima de la superficie PR5. Esta sección enumera los nuevos invariantes, los nuevos tests y reconfirma el verdict.

### Nuevos invariantes

| Invariante | Superficie | Dónde vive |
|---|---|---|
| `apply_web_to_legacy(client, table_name, *, web_snapshot, dry_run, lock_path)` es un entry point público de reverse-applier | Reusa `execute_legacy_sql` (PR1) y un nuevo symmetric `execute_legacy_write` seam (`migration.dysflow_client.execute_legacy_write`); MSACCESS pre-flight + lock + snapshot todos mirroran el forward path | `migration/apply_reverse.py`; `migration/dysflow_client.py::execute_legacy_write`; `migration/legacy_reader.py::set_legacy_write_executor` |
| `migration.semantic_events.record_lifecycle_reversed(...)` emite un evento `LIFECYCLE_REVERSED` con `source_direction="web-to-legacy"` | El reverse applier invoca el emisor una vez por cambio de estado de derived-column observado entre forward y reverse apply | `migration/semantic_events.py`; `migration/apply_reverse.py::_emit_reversed_lifecycle_events_for_changed_derived` |
| `migration.cli.APPLY_DIRECTION_WEB_TO_LEGACY` flag threaded a través de `run_apply` | El default CLI sigue siendo `legacy-to-web` (backward compat); `--direction web-to-legacy` dispatcha a `apply_web_to_legacy` | `migration/cli.py::build_parser` + `run_apply` |
| Per-strategy table honrado simétricamente en reverse (`preserve` avanza `last_legacy_snapshot_at`, `derived` no re-deriva, `fixed` nunca se escribe) | El reverse applier nunca escribe `preserved_value` (pineado por `tests/migration/test_reverse_apply.py::test_preserve_column_not_written_to_legacy` static grep); el derivation engine nunca se invoca en reverse (pineado por `test_derived_column_no_rederive_on_reverse`) | `migration/apply_reverse.py::_advance_preserve_shadow_state` |
| Drift detection en reverse: rowcount=0 → registra shadow row `needs_review` con `review_reasons=["reverse_drift_legacy_row_missing"]` | El operador resuelve vía `apap-migrate reconcile --filter-direction web-to-legacy` | `migration/apply_reverse.py::_record_drift_needs_review` (pineado por `tests/migration/test_round_trip.py::test_round_trip_detects_unsynced_edits_as_needs_review`) |

### M2 verdict (re-confirmado)

PASS para el M2 reverse path. Los invariantes de round-trip (`tests/migration/test_round_trip.py`, 5 átomos) se ejercitan vía `FakeLocalBackend` + injected legacy executor + injected legacy write seam; sin mutación de backend real. La disciplina de redacción PII (lista cerrada de 15 campos) y los invariantes de autorización de PR4b / PR5 no cambian — el reverse applier pasa por `app.core.logging.log_safe` (15 campos scrubed) y nunca toca el bucket de storage (forward-only).

### Operator acknowledgement

El operador must revisar y aceptar este verdict como parte de la M1 acceptance gate antes de reclamar "Usable ya". La aceptación se registra en el migration report (`migration_report.json` + `migration_report_signature.json`) según la sección "Escalation" del runbook de apply.

## References

- `app/core/logging.py::REDACTED_FIELDS` (15 entradas).
- `app/main.py:148` (`PUBLIC_PATHS` 5-entry shape).
- `app/modules/animals/adapters/local-backend/animals_local_backend_photo.py` (placeholder, sentinel y resolución de media type).
- `app/modules/animals/routes.py` (auth short-circuit + 404 translation + Response build).
- `migration/mappings/voluntario.yaml` (`DNI: legacy_column: null`).
- `migration/apply.py` (`apply_legacy_to_web(dni_collision_counter=...)` DI seam).
- `migration/apply_reverse.py` (`apply_web_to_legacy`, `_advance_preserve_shadow_state`, `_record_drift_needs_review`).
- `migration/dysflow_client.py::execute_legacy_write`.
- `migration/dni_collision.py::DniCollisionCounter`, `record_dni_collision(direction=...)`.
- `migration/cli.py::build_parser` (`--filter-direction`), `_is_pii_web_column`, `_mask_pii_value`, `_looks_like_pii`.
- `migration/semantic_events.py::record_lifecycle_reversed`.
- `migration/shadow_state.py::list_needs_review(origin_direction=...)`, `ShadowStateRepository.upsert(origin_direction=...)`.
- `docs/runbooks/live-migration-apply.md` (apply / pre-flight / rollback / escalation).
- `docs/runbooks/auth-email-normalization.md` (limpieza one-shot de filas heredadas con casing mixto).
- Tests:
  - `tests/test_logging.py`
  - `tests/test_log_safe_redaction.py`
  - `tests/test_logging_redaction_adversarial.py`
  - `tests/migration/test_pii_redaction.py`
  - `tests/migration/test_dni_collision.py`
  - `tests/migration/test_dni_collision_counting.py`
  - `tests/migration/test_storage_methods.py`
  - `tests/migration/test_cli.py`
  - `tests/test_public_paths.py`
  - `tests/test_animals_foto_route.py`
  - `tests/test_animals_local_backend_adapter.py`
  - `tests/test_runbook_links.py`
  - `tests/test_pii_audit_doc.py`
- AGENTS.md §9 (`log_safe`), §10 (CSRF), §13 (runbook), §18 (web ↔ legacy mutual exclusion + sync), §23 (E2E).
