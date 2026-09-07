[← Back to README](../../README.md)

# live-migration-apply.md

> **Alcance**: pipeline forward de PR3/M1 para la migración legacy ACCDB → LocalBackend. Cubre cada error de apply (salidas 5/6/7), cada evidencia, dry-run, pre-flight y reversión.

> **Audiencia**: operador con Microsoft Access Database Engine, `.accdb` legado y clave de servicio de LocalBackend. No aplica a producción.

## Quick Navigation

| Sección | Propósito |
|---|---|
| When to trigger | Disparadores en terminal del operador o en registros CI |
| Pre-deploy checklist | Requisitos del entorno y de credenciales |
| Deploy steps | Secuencia dry-run, apply real y verificación |
| Verification | Códigos de salida, drift, eventos auditados y archivos escritos |
| Rollback | Reversión por categoría de salida |
| PR4b — Almacenamiento de fotos y display autenticado | Capa de fotos privadas sobre el pipeline de apply |
| Dirección inversa (PR6 / M2) | Aplicador simétrico web → legacy |
| Escalada | Procedimiento cuando el runbook no resuelve el incidente |

## When to trigger

Abra este runbook cuando aparezca alguna de las siguientes señales en el terminal del operador o en los registros CI:

- Un comando `apap-migrate apply` sale con **código 5** (preflight, lectura legada, o fallo de bootstrap de infraestructura), **código 6** (drift de origen), o **código 7** (interrupción de partial-apply).
- Un evento `log_safe("apply.preflight_unavailable", reason=…)` aparece en el flujo JSON de auditoría.
- Un archivo `migration.lock_snapshot.json` aparece bajo `<migration_dir>/`.
- Un archivo `migration.partial_apply.json` aparece bajo `<migration_dir>/` (es **siempre** evidencia visible para el operador; PR3 no reanuda automáticamente).
- El operador necesita verificar una aplicación previamente completada (comprobación de drift contra el último snapshot).
- El `.accdb` legado se editó entre dos ejecuciones de apply y el operador quiere entender el drift.

no use este runbook para:

- Bootstrap M0 / shadow-table / bucket privado de infraestructura — consulte `docs/runbooks/live-migration-m0-bootstrap.md`.
- Dirección inversa (web → legacy) — fuera del alcance de PR3; vea el PR6 de seguimiento.

## Pre-deploy checklist

Antes de ejecutar `apap-migrate apply` por primera vez en una estación del operador, todos los puntos siguientes deben verificarse. Cada punto es una compuerta dura: cualquier fallo aborta el apply con un error categórico y una referencia estable al runbook.

- [ ] **Python ≥ 3.11** instalado (`python --version`).
- [ ] **`psutil` instalado e importable** (`python -c "import psutil; print(psutil.__version__)"`). Sin `psutil`, el preflight MSACCESS falla cerrado con `reason=psutil_missing`. El runbook documenta esto como requisito duro, no advertencia soft-fail.
- [ ] **Microsoft Access Database Engine** (redistribuible) instalado (`python -c "import pyodbc; print(pyodbc.drivers())"` debe listar `Microsoft Access Driver (*.accdb)`). El ejecutor (`migration/legacy_access_client.py`) eleva `LegacyReaderError` (CLI exit 5, reason `legacy_read_failed`) si falta el driver.
- [ ] **Microsoft Access está cerrado** en la estación del operador. El preflight MSACCESS (`migration/lock.check_msaccess_running`) eleva `MsAccessRunningError` (CLI exit 5, reason `msaccess_running`) cuando cualquier proceso `MSACCESS.EXE` está vivo. Cierre el frontend de Access y reintente.
- [ ] **El bucket privado `apap-photos` de LocalBackend existe** y es privado (`isPublic=false`). El bootstrap (M0) se ejecutó con éxito — consulte `docs/runbooks/live-migration-m0-bootstrap.md` para el checkpoint del operador `ensure-bucket`. Un bucket ausente o público aborta con `infra_bootstrap_failed`.
- [ ] **`APAP_MIGRATION_DIR`** apunta a un directorio escribible para `migration.lock`, `migration.lock_snapshot.json` y `migration.partial_apply.json`. Por defecto: `./migration/`.
- [ ] **`APAP_INSFORGE_URL`** y **`APAP_INSFORGE_SERVICE_KEY`** están fijados en el entorno del operador (o el cargador de configuración de producción los recoge). El apply necesita privilegio de service key para escribir filas en la tabla shadow y operaciones sobre el bucket.
- [ ] **`APAP_LEGACY_ACCDB_PATH`** apunta al `.accdb` legado con acceso de lectura. La variable se documenta en `migration/legacy_access_client.py`.
- [ ] **Un directorio de origen estable**: el `.accdb` legado y el directorio de fotos se mantienen estables (sin ediciones concurrentes) durante toda la duración del apply. El snapshot escrito al inicio del apply sella sus huellas SHA-256; cualquier cambio posterior aborta el apply (detección de drift, véase Verificación §"Drift").

## Deploy steps

El pipeline de apply es un único comando. El flujo recomendado es:

1. **Dry-run primero** — sólo conteo, sin escrituras, sin lock, sin snapshot:

       apap-migrate apply --table animal --voluntario --entrada \
           --legacy-path $APAP_LEGACY_ACCDB_PATH \
           --check-only

   El CLI imprime líneas por tabla del tipo `would insert=N skipped=M errors=K`. Inspeccione los conteos antes de continuar. `--check-only` omite por completo el preflight MSACCESS y el lock (comparación de sólo lectura).

2. **Resuelva evidencia parcial de una ejecución interrumpida previa** (si existe):

       ls $APAP_MIGRATION_DIR/migration.partial_apply.json

   Si el archivo existe, la ejecución previa se interrumpió (SIGINT o crash). PR3 deliberadamente no reanuda automáticamente. Revise la carga útil JSON (`direction`, `table_name`, `progress_applied`, `progress_total`, `reason`, `recorded_at`). Cuando esté listo:

       rm $APAP_MIGRATION_DIR/migration.partial_apply.json

3. **Apply real** — emite `migration.lock_snapshot.json` y ejecuta el pipeline forward:

       apap-migrate apply --table animal --voluntario --entrada \
           --legacy-path $APAP_LEGACY_ACCDB_PATH

   El CLI sale con 0 en éxito, 1 en errores por fila (los diffs continúan), 5/6/7 en fallos categóricos (véase Verificación §"Códigos de salida").

4. **Verifique** (véase Verificación) antes de ejecutar otro apply.

## Verification

### Códigos de salida (vocabulario cerrado, coincide con la salida del CLI)

| Salida | Razón | Significado | Acción del operador |
|---|---|---|---|
| 0 | n/a (éxito) | Apply completado; `migration.lock_snapshot.json` escrito. | Revise los conteos por tabla; concilie divergencias en la tabla shadow. |
| 1 | n/a (errores parciales) | Al menos un error por fila (por ejemplo, fila legada sin clave natural). | Lea las líneas `errors=`; corrija los datos; reintente. El snapshot ya se escribió. |
| 2 | error de uso | Argumentos CLI incorrectos (tabla desconocida, timestamp mal formado, web_client ausente). | Corrija los argumentos; reejecute. |
| 5 | `msaccess_preflight_unavailable` | `psutil` ausente o `process_iter` elevó a mitad de iteración. | Instale `psutil`; reejecute. **No** proceda sin psutil. |
| 5 | `msaccess_running` | Se detectó un proceso `MSACCESS.EXE` vivo. | Cierre Access; reejecute. |
| 5 | `legacy_read_failed` | Fallo de E/S pyodbc (driver ausente, `.accdb` bloqueado, red, o **`conn.commit()` elevó en la frontera de escritura** — issue #218 aflora esto como `LegacyWriteCommitFailed` tipado, de modo que el operador ve la línea categórica en lugar de un gap silencioso de durabilidad). | Instale Access Driver / desbloquee `.accdb` / verifique la ruta; reejecute. |
| 5 | `infra_bootstrap_failed` | Bucket privado `apap-photos` ausente o público; tabla shadow rota. | Reejecute el bootstrap M0; verifique visibilidad del bucket; reejecute apply. |
| 6 | `source_drift` | `migration.lock_snapshot.json` no coincide con las huellas actuales del origen. | Inspeccione qué cambió en `.accdb` o en las fotos; decida y proceda. |
| 7 | `partial_apply_interrupted` | `migration.partial_apply.json` existe de una ejecución interrumpida previa. | Revise la evidencia; `rm` el archivo; reejecute. **Sin reanudación automática.** |

El CLI imprime una línea por error en el formato canónico:

    apap-migrate apply: status=error reason=<cat> exit=<N> runbook=docs/runbooks/live-migration-apply.md

Sin traceback, sin PII sin procesar (DNI/Email/Tel1/Tel2), sin rutas de sistema de archivos sin procesar. El operador consulta este runbook para la interpretación detallada.

### Detección de drift (salida 6 `source_drift`)

El apply escribe `migration.lock_snapshot.json` después de adquirir el lock y antes de la primera lectura legada. El snapshot registra el SHA-256 del `.accdb` y un manifiesto determinista del directorio de fotos (nombre de archivo + tamaño + SHA-256 ordenados por nombre de archivo).

En la siguiente ejecución de apply, el pipeline recalcula las huellas y las compara con el snapshot en disco. **Cualquier** diferencia (hash del accdb o hash del manifiesto de fotos) aborta el apply con `source_drift` (salida 6). El operador nunca debe confiar en un apply que excede la ventana de drift.

Para inspeccionar el drift:

    diff <(jq -S . $APAP_MIGRATION_DIR/migration.lock_snapshot.json) \
         <(jq -S . /tmp/current_snapshot.json)

Los campos `accdb_sha256_changed`, `photos_dir_sha256_changed`, `photos_file_count_delta` y `photos_total_bytes_delta` en el objeto de excepción indican al operador qué lado cambió y en qué medida. PR3 falla cerrado; un PR futuro puede añadir `--accept-drift` para reconocimiento explícito.

### Eventos de auditoría `log_safe` (visibles para el operador vía JSON stdout)

- `apply.preflight_unavailable` — emitido cuando `check_msaccess_running` eleva. Lleva solo el campo `reason` categórico (`psutil_missing` o `process_iteration_failed`). Sin PIDs, sin cadenas de error, sin rutas.
- `sync.applied` — auditoría por fila (superficie existente de PR3).

### Archivos escritos por el apply

| Ruta | Ciclo de vida |
|---|---|
| `<migration_dir>/migration.lock` | Escrito al inicio del apply; liberado al final (éxito O error). |
| `<migration_dir>/migration.lock_snapshot.json` | Escrito después del lock, antes de la primera lectura. Sobreescrito en cada apply real (no en dry-run). La detección de drift lo lee en la siguiente ejecución. |
| `<migration_dir>/migration.partial_apply.json` | Escrito en SIGINT después de que el snapshot ya se escribió. no se limpia automáticamente (sin limpieza destructiva por directiva del operador). El operador debe revisarlo y borrarlo con `rm`. |
| Filas en `web_only_feature_shadow` (por divergencia) | Registradas en la tabla shadow cuando una fila web discrepa de una fila legada. El operador concilia con `apap-migrate reconcile --interactive` (fuera del alcance de PR3; superficie preexistente de PR5). |

### Lo que no se reanuda automáticamente

- `migration.partial_apply.json` **nunca** se reanuda automáticamente. PR3 bloquea el siguiente apply con salida 7 (`partial_apply_interrupted`) hasta que el operador elimine el archivo manualmente. La reanudación automática es una tarea de seguimiento (per `tasks.md` 9.1; programada antes de la compuerta M2 fallback-ready).
- `migration.lock_snapshot.json` **nunca** se fusiona automáticamente entre ejecuciones. Cada apply sobrescribe el snapshot previo con las huellas nuevas. El drift se detecta en la siguiente ejecución; el operador decide.
- La configuración de bucket público **nunca** se recupera automáticamente. `bootstrap_m0_infrastructure` aborta el apply con `infra_bootstrap_failed` (salida 5) si el bucket falta o es público. El operador debe arreglar el bucket mediante el MCP de LocalBackend antes de reintentar.

### Lo que no se registra

- **Ninguna PII sin procesar** (valores de columna DNI / Email / Tel1 / Tel2) aparece en eventos `log_safe` o en la salida del CLI. La lista de redacción de PII en `app/core/logging.py` es el vocabulario cerrado.
- **Ninguna ruta de sistema de archivos sin procesar** (por ejemplo `C:\Users\…`, `/var/…`, `/tmp/…`, `/home/…`) aparece en el flujo del operador. El campo `detail` de la excepción puede contener contexto interno, pero el CLI sólo emite la razón categórica.
- **Ninguna carga útil de excepción sin procesar** (por ejemplo fragmentos SQL completos, tracebacks pyodbc completos) aparece en el flujo del operador. Los operadores ven una línea categórica estable; el detalle verboso vive en los registros estructurados a discreción del operador.

## Rollback

La disciplina de reversión depende de si el apply tuvo éxito o se abortó.

### Reversión tras apply exitoso (salida 0)

El apply es **idempotente** sobre el origen: el mismo `.accdb` y el mismo directorio de fotos producen las mismas huellas de snapshot. Para volver a ejecutar un apply exitoso:

1. Las filas de la base de datos web destino ya están insertadas; volver a ejecutar recalcula la búsqueda por clave natural de cada fila y omite no-ops.
3. Las divergencias (filas web existentes con una carga útil diferente) aterrizan en `web_only_feature_shadow` como filas `needs_review`. El operador concilia con `apap-migrate reconcile --interactive` (superficie preexistente de PR5; fuera del alcance de PR3).
4. `migration.lock_snapshot.json` se sobrescribe en la siguiente ejecución; no se requiere limpieza manual.

### Reversión tras interrupción de partial-apply (salida 7 `partial_apply_interrupted`)

La ejecución previa de apply se interrumpió (SIGINT, crash, OOM o aborto iniciado por el operador). El destino puede tener algunas filas insertadas y otras no. PR3 deliberadamente no reanuda automáticamente.

1. **no elimine las filas del destino** sin consultar primero el registro del operador y `migration.lock_snapshot.json` (para saber qué huellas de origen estaban vigentes al inicio del apply) y `migration.partial_apply.json` (para saber hasta dónde progresó el apply).
2. Revise la carga útil de `migration.partial_apply.json`:

       jq . $APAP_MIGRATION_DIR/migration.partial_apply.json

   Campos: `schema_version`, `direction`, `table_name`, `progress_applied`, `progress_total` (anulable), `reason`, `recorded_at`.

3. Complete las filas faltantes manualmente (psql / editor SQL) O ejecute `apap-migrate apply` de nuevo después de eliminar el archivo parcial (el apply es idempotente sobre búsquedas por clave natural y omite filas ya presentes).
4. Una vez que el destino sea consistente con el origen, `rm $APAP_MIGRATION_DIR/migration.partial_apply.json`.
5. **Nunca** edite `migration.partial_apply.json` a mano — el archivo sólo es parseable como JSON; las ediciones manuales producen drift en la siguiente ejecución.

### Reversión por drift (salida 6 `source_drift`)

El origen cambió entre el apply previo y el actual. El destino puede ser consistente con el origen viejo pero inconsistente con el origen nuevo. Opciones, en orden de preferencia:

1. **Investigue el drift primero.** Use los campos `accdb_sha256_changed`, `photos_dir_sha256_changed`, `photos_file_count_delta` y `photos_total_bytes_delta` en la excepción para acotar el cambio:

       # Inspeccione el snapshot previo
       jq . $APAP_MIGRATION_DIR/migration.lock_snapshot.json

       # Calcule las huellas actuales manualmente (véase migration/lock_snapshot.py)

   Si el cambio es intencional (por ejemplo, el operador editó el origen a propósito), reejecute el apply después de respaldar las filas destino que quiera preservar. El apply es idempotente sobre búsquedas por clave natural y omite filas ya presentes.

2. **Si el cambio no es intencional** (por ejemplo, una escritura parcial en `.accdb`), DETÉNGASE. no reejecute. Restaure el origen desde la copia de seguridad, luego reejecute.

### Reversión por fallo de preflight / lectura legada / bootstrap de infraestructura (salida 5)

Estos fallos ocurren antes de escribir cualquier dato. No hay nada que revertir. Corrija el problema subyacente:

- `msaccess_preflight_unavailable` → `pip install psutil`.
- `msaccess_running` → cierre Microsoft Access.
- `legacy_read_failed` → instale el redistribuible de Microsoft Access Database Engine, O cierre cualquier bloqueo retenido sobre `.accdb`, O verifique la ruta legada.
- `infra_bootstrap_failed` → reejecute el bootstrap M0 (`apap-migrate ensure-bucket apap-photos --check-only`); verifique la visibilidad del bucket; consulte `docs/runbooks/live-migration-m0-bootstrap.md`.

Tras corregir el problema, reejecute el apply. Los archivos lock + snapshot se liberan / sobrescriben limpiamente.

## PR4b — Almacenamiento de fotos y display autenticado

PR4b dispone la superficie de display privado de fotos sobre el pipeline de apply. El apply mueve `animales.nombrefoto` desde el nombre de archivo legado a la clave de objeto canónica devuelta por la estrategia de subida; la nueva ruta `GET /animales/{animal_id}/foto` transmite bytes desde el bucket privado `apap-photos` con credenciales del lado servidor.

### Cuándo abrir este runbook (PR4b)

Use esta sección cuando aparezca alguna de las siguientes señales:

- El bucket `apap-photos` falta O tiene `isPublic=true`; el preflight del apply aborta con `infra_bootstrap_failed` (salida 5) y el mensaje apunta a `bucket_public_violation` o `bucket_visibility_unknown`.
- Una pasada de migración de fotos termina con `MigrationReport.warnings` cargando `photo.file_missing`, `photo.bytes_corrupt`, `photo.unsupported_ext` o `photo.dir_unreachable`. La pasada no aborta — se escriben filas centinela `__missing__` — pero el operador quiere inspeccionar las filas afectadas.
- `GET /animales/{animal_id}/foto` (UUID) devuelve 200 con bytes que parecen rotos, o devuelve 200 con el PNG de placeholder para una fila que el operador sabe que tiene una foto real.
- El contrato 404-idempotente de `delete_object` está en duda: el operador eliminó un objeto manualmente y quiere verificar que el siguiente `apap-migrate status --photos` reporta `orphan_count=0` para esa clave.

### Lista de comprobación previa (PR4b)

Además de la lista global anterior, cada operador de PR4b debe verificar:

- [ ] **El bucket `apap-photos` existe y es privado** — verificado por `python -m migration ensure-bucket apap-photos --check-only` que devuelve `is_public=false`. Un bucket público debe recrearse como privado antes de reintentar cualquier operación de fotos.
- [ ] **El spike de contrato de almacenamiento es PASS** — confirmado por `docs/discovery/storage-contract-2026-Q3.md` cargando `Verdict: PASS` y `PR4b gate: PASS`. Los endpoints canónicos pineados + cabeceras de autenticación en ese artefacto deben coincidir con los métodos `upload_object`/`download`/`delete` de `app/core/local_backend.py`.
- [ ] **LocalBackend en vivo alcanzable** — `python -c "import httpx; httpx.get(settings.local_backend_url + '/api/storage/buckets', headers={'Authorization': f'Bearer {settings.local_backend_service_key}'})"` devuelve 2xx. La accesibilidad de red es un precondición para cualquier migración o display de fotos.
- [ ] **`APAP_INSFORGE_URL` + `APAP_INSFORGE_SERVICE_KEY`** están cargados por `app.core.config.get_settings` desde el entorno del operador. Los CLIs (`apap-migrate`, `python -m migration storage_spike`) invocan `get_settings.cache_clear()` + recarga para que el env tenga precedencia sobre cualquier `.env` obsoleto.
- [ ] **El directorio de fotos es estable** — sin ediciones concurrentes sobre `URLDirectorioDocumentacion` durante toda la duración del apply. La detección de drift (salida 6) aborta ante cualquier cambio.
- [ ] **El veredicto de auditoría es PASS** — `docs/audits/pii-live-migration-2026-Q3.md` carga `Verdict: PASS`. La aceptación de M1 queda bloqueada sin él.

### Pasos de despliegue (PR4b)

El flujo PR4b es una migración forward que se ejecuta sobre el apply estándar `apap-migrate apply`. El apply emite objetos `apap-photos` como efecto colateral de la pasada de tabla `animal` (cuando `animal.yaml` carga el bloque de storage y la pasada `migration/apply.py` correspondiente se ejecuta). El flujo recomendado:

1. **Dry-run de la pasada de fotos** — confirme los conteos antes de tocar el almacenamiento:

       apap-migrate apply --table animal \
           --legacy-path $APAP_LEGACY_ACCDB_PATH \
           --check-only

   `--check-only` no escribe el snapshot, no bloquea y no emite objetos `apap-photos`. Sólo cuenta filas legadas y emite la línea `would insert=N` para revisión.

2. **Apply real** — ejecuta el pipeline forward. La pasada de fotos se ejecuta como parte de la escritura de la tabla `animal`; las fotos por fila se suben vía `LocalBackendClient.upload_object` (flujo S3-compatible de tres pasos: estrategia → transferencia → confirmación opcional). Los bytes duplicados se omiten porque el cliente propone `filename=<sha256>.<ext>` y el servidor deduplica por la clave.

       apap-migrate apply --table animal \
           --legacy-path $APAP_LEGACY_ACCDB_PATH

   El CLI sale con 0 en éxito, 5/6/7 en fallos categóricos (véase la tabla global de §"Verificación" códigos de salida).

3. **Verifique** — confirme invariantes del bucket y comportamiento de display antes de ejecutar otro apply:

       apap-migrate status --photos
       apap-migrate verify-storage --check-bytes     # no en CI; spot-check del operador
       curl -b "$APAP_SESSION_COOKIE" \
           https://app.example/animales/<uuid>/foto -o /tmp/foto.bin

   `status --photos` reporta `unique_objects=N`, `row_references=N`, `orphan_count=K`. Los huérfanos son objetos en el bucket que ninguna referencia de `animales.nombrefoto` apunta; `--cleanup-orphans` los elimina idempotentemente.

### Verificación (PR4b)

**Invariantes del bucket**

| Comprobación | Cómo verificar | Criterio de aprobación |
|---|---|---|
| `apap-photos` es privado | `apap-migrate ensure-bucket apap-photos --check-only` | `is_public=false` |
| El conteo de objetos del bucket coincide con las referencias de fila | `apap-migrate status --photos` | `orphan_count=0` |
| Sin URL prefirmada filtrada vía `GET /foto` | Inspeccione las cabeceras de respuesta con `curl -I` | Sin fugas de `Location`/`X-Trace-Id`/Set-Cookie/etc. |
| Sin PII en cargas útiles de `log_safe` | `pytest tests/test_log_safe_redaction.py` | 13 átomos en verde |

**Fallos de display**

| Síntoma | Causa probable | Acción del operador |
|---|---|---|
| `GET /animales/{id}/foto` devuelve 200 con PNG de placeholder | Centinela / `NombreFoto` ausente / 404 de almacenamiento | Inspeccione `animales.nombrefoto` para la fila; verifique que el objeto existe en el bucket. |
| `GET /animales/{id}/foto` devuelve 302 `/login` | Sin cookie de sesión | Esperado. Redirección del middleware de autenticación; el handler nunca ve llamadas anónimas. |
| `GET /animales/{id}/foto` devuelve 404 | UUID del animal no encontrado en `animales` | Inspeccione el UUID; es esperado para filas soft-deleted (`activo=false`). |
| `GET /animales/{id}/foto` devuelve 200 con bytes vacíos | Transporte de almacenamiento agotado antes de que llegaran los bytes | Reejecute tras `apap-migrate verify-storage --check-bytes`. |
| `apap-migrate status --photos` reporta huérfanos inesperados | Un apply previo se ejecutó con un conjunto de fotos distinto | Ejecute `apap-migrate status --photos --cleanup-orphans` (idempotente). |

### Archivos escritos por PR4b

| Ruta | Ciclo de vida |
|---|---|
| `apap-photos` (bucket LocalBackend) | Creado por el bootstrap M0; carga los objetos de foto. nunca auto-eliminado por el apply. |
| `animales.nombrefoto` (columna web) | Fijada por fila por la pasada de fotos; almacena la clave **devuelta** (el servidor puede renombrar). |
| `migration_report.json` → `warnings` | Array de entradas `photo.<razón>` (filas centinela por fotos ausentes / corruptas / no soportadas). |
| `migration_report.json` → `counts.apap_photos` | `{count_legacy: N, count_web: N}` (objetos vs filas que los referencian). |
| `migration_report.json` → `source_hashes.apap-photos` | SHA-256 del manifiesto de fotos, detectado por drift en el siguiente apply. |

### Lo que PR4b no hace

- **no** se devuelve ninguna URL prefirmada al navegador/cliente. La ruta transmite bytes vía `httpx.Client.stream` con bearer auth; el cliente sólo ve el cuerpo de la respuesta.
- **no** hay configuración de bucket público. La invariante de bootstrap (`is_public=false`) se aplica pre-red y en cada ejecución de apply.
- **no** hay auto-limpieza de huérfanos en CI. `--cleanup-orphans` es un comando explícito del operador, nunca un paso automático.
- **no** hay re-hash del lado servidor de los bytes subidos. El comando `apap-migrate verify-storage --check-bytes` es un spot-check iniciado por el operador; no está en CI.
- **no** hay PII en los registros. La lista de redacción de `log_safe` cuenta con quince entradas (`email`, `tel1`, `tel2`, `dni` añadidos por PR4b); cada átomo en `tests/test_log_safe_redaction.py` RED-first prueba el contrato.

### Reversión (PR4b)

La reversión de PR4b se dispone sobre la §"Reversión" global anterior. El orden de preferencia no destructivo:

1. **Desactive el display primero** — fije `app_settings.FOTO_ROUTE_ENABLED=false` (feature flag, no enviado en PR4b) para que `GET /animales/{id}/foto` devuelva 404 en lugar de bytes. Esta es la reversión más segura en producción: el bucket queda intacto, las filas quedan intactas y los usuarios no ven imágenes rotas.
2. **Verifique que el bucket está respaldado** — ejecute `apap-migrate status --photos > photos_before_rollback.json` antes de cualquier paso destructivo. El operador debe contar con una instantánea de `photos_before_rollback.json` (o una copia externa del bucket) antes de eliminar nada.
3. **Marque filas como centinela** — si el problema es display corrupto en lugar de almacenamiento ausente, ejecute `apap-migrate reconcile --interactive --table animales` y elija `mark sentinel` por fila. La ruta sirve entonces el placeholder sin E/S de almacenamiento.
4. **Elimine el bucket** (último recurso, nunca sin respaldo) — `delete-bucket apap-photos` vía el MCP de LocalBackend. Tras la eliminación del bucket, `GET /animales/{id}/foto` continúa devolviendo 200 con PNG de placeholder (la ruta captura el 404 de almacenamiento y cae al fallback). Las filas `animales.nombrefoto` conservan la clave SHA-256 pero devuelven `404` en la comprobación de status del siguiente apply; el operador resuelve con `apap-migrate reconcile --interactive`.

La reversión nunca es destructiva de:

- El `.accdb` legado (contrato de sólo lectura).
- Las tablas de dominio de LocalBackend (`animales`, `voluntarios`, `entradas`).
- La tabla `web_only_feature_shadow` (historial de auditoría/divergencia).
- El `migration.lock_snapshot.json` (los re-applies lo sobrescriben).

`TRUNCATE web_only_feature_shadow` y `DROP TABLE web_only_feature_shadow` están explícitamente no recomendados — destruyen el historial de divergencia y la evidencia de round-trip.

## Dirección inversa (PR6 / M2)

PR6 envía el aplicador inverso simétrico de modo que el operador pueda ejecutar ``apap-migrate apply --direction web-to-legacy`` tras la aplicación forward. El camino inverso reutiliza cada costura del camino forward (lock, preflight MSACCESS, snapshot, guarda partial-apply, actualización transaccional de ``sync_state.json``) más los hooks exclusivos del inverso:

- ``migration/reverse_apply/orchestrator.py::apply_web_to_legacy`` (línea 363) es el punto de entrada. Firma: ``apply_web_to_legacy(client, table_name, *, legacy_path, web_snapshot, dry_run, lock_path, dni_collision_counter)``. (migrated: el runbook histórico citaba `migration/apply_reverse.py`; la implementación consolidada reside ahora en `migration/reverse_apply/orchestrator.py`.)
- ``migration/legacy_reader.py::execute_legacy_write`` (línea 213) es la frontera de escritura basada en pyodbc (espejo de ``execute_legacy_sql``). Los inserts y updates devuelven ``int`` rowcount; ``0`` activa el grabador de drift. (migrated: el runbook histórico citaba `migration/legacy_access_client.py`; el seam de escritura se encuentra ahora en `migration/legacy_reader.py`.)
- ``migration/cli_apply_reverse.py::APPLY_DIRECTION_WEB_TO_LEGACY`` bandera enhebrada a través de ``run_apply``. El valor por defecto sigue siendo ``legacy-to-web`` de modo que los llamadores de M1 permanezcan en verde.
- La tabla per-estrategia de la spec de preservación se honra simétricamente: ``preserve`` avanza ``last_legacy_snapshot_at`` y **nunca escribe** ``preserved_value``; ``derived`` no re-deriva; ``fixed`` es bootstrap de una sola vez y nunca se escribe en reverse.
- Detección de drift: cuando la frontera de escritura legada reporta ``rowcount == 0`` (fila de clave natural eliminada en legacy entre forward + reverse), la divergencia se registra como ``needs_review`` con ``review_reasons=["reverse_drift_legacy_row_missing"]``. El operador resuelve con ``apap-migrate reconcile --filter-direction web-to-legacy``.

### Cuándo abrir este runbook (inverso)

- Una edición del lado web necesita aterrizar en la estación del operador (por ejemplo, el operador rellenó un override ``current_state`` en la UI web entre forward y reverse).
- El apply forward se ejecutó hace N minutos y el operador quiere reconverger sin una re-ejecución completa.
- Se está ejerciendo una compuerta de aceptación M2 (prueba round-trip, auditoría).

### Lista de comprobación previa (inverso)

- El ``migration.lock_snapshot.json`` del apply forward existe y coincide con el ``.accdb`` actual (sin drift).
- ``partial_apply.json`` está ausente (un reverse previo no se interrumpió).
- ``apply --direction web-to-legacy --check-only`` reporta un conteo ``would_apply`` sensato (revisión visual del operador — aún no hay umbral automatizado).
- ``web_only_feature_shadow.preserved_value`` es byte-idéntico al estado post-forward para cada columna preserve (el aplicador inverso sólo avanza ``last_legacy_snapshot_at``).

### Pasos de despliegue (inverso)

1. ``apap-migrate apply --direction web-to-legacy --table voluntario --legacy-path $APAP_LEGACY_ACCDB_PATH --check-only`` → previsualice el diff. Registra ``would_apply=N`` en stdout.
2. ``apap-migrate apply --direction web-to-legacy --table voluntario --legacy-path $APAP_LEGACY_ACCDB_PATH`` → ejecución real. Cada fila aplicada emite ``log_safe("sync.applied", direction="web->legacy", ...)`` con la clave natural + ``source_hash``. Los cambios de estado de columnas derivadas emiten eventos ``LIFECYCLE_REVERSED``.
3. ``apap-migrate reconcile --filter-direction web-to-legacy --check-only`` → liste cualquier fila ``needs_review`` que el grabador de drift haya producido (clase legacy-row-missing).

### Verificación (inverso)

- ``MigrationReport.collisions[<tabla>]["preserve_advances"]`` coincide con el conteo en tiempo de ejecución de filas shadow ``reverse_drift_legacy_row_missing`` + sombreados manuales ``dni_collision``.
- ``sync_state.tables[<tabla>].last_sync_at`` avanzó más allá del valor pre-apply; el archivo pre-apply es byte-idéntico cuando no se aplicaron filas (contrato atómico ``save_sync_state``).

### Archivos escritos (inverso)

- ``migration.partial_apply.json`` si SIGINT golpea a mitad de ejecución (el operador debe eliminarlo antes de reintentar, mismo contrato que forward).
- ``sync_state.json`` avanza ``tables[<tabla>].last_sync_at``.
- ``migration/dni_collision.py::record_dni_collision`` (línea 109) se invoca para cada columna preserve con un valor del lado web (por ejemplo ``DNI`` en ``voluntarios``); el contador se incrementa de modo que el CLI `reconcile` de PR7 pueda exponer el conteo.

### Reversión (inverso)

El apply inverso es idempotente en re-ejecución: las filas cuya carga útil mapeada ya coincide con legacy se omiten; las filas ``needs_review`` permanecen ``needs_review`` hasta que el operador resuelve vía el flujo ``reconcile --interactive``. No se requiere limpieza destructiva.

## Escalada

Si el runbook no resuelve el incidente:

1. Capture las líneas de salida del CLI — son el contrato categórico canónico.
2. Capture `migration.lock_snapshot.json` + `migration.partial_apply.json` (si está presente) y el evento JSON `apply.preflight_unavailable` (si está presente) desde stdout.
3. Abra un issue de seguimiento con `type:bug` y etiqueta `migration:apply`. Referencie el SHA de commit del apply más reciente + el SHA de `migration.lock_snapshot.json`.

## Documentos relacionados

- `migration/apply.py` — pipeline de apply forward.
- `migration/reverse_apply/orchestrator.py` — pipeline inverso (PR6).
- `migration/legacy_reader.py` — frontera de lectura/escritura legada (`execute_legacy_write`, `LegacyWriteCommitFailed`).
- `migration/lock.py` y `migration/lock_snapshot.py` — preflight MSACCESS y detección de drift.
- `migration/bootstrap.py` — `ensure_bucket` y `BucketEnsureResult` para `apap-photos`.
- `migration/dni_collision.py` — `record_dni_collision` para columnas preserve.
- `migration/shadow_state.py` — DDL de `web_only_feature_shadow`.
- `migration/storage_spike.py` — spike del contrato de almacenamiento (PR4b gate).
- `app/core/local_backend.py` — `upload_object` (flujo S3 de tres pasos).
- `app/core/logging.py` — lista de redacción de PII (quince entradas tras PR4b).
- `docs/runbooks/live-migration-m0-bootstrap.md` — bootstrap de infraestructura (M0).
- `docs/audits/pii-live-migration-2026-Q3.md` — veredicto de auditoría PII.
- `docs/discovery/storage-contract-2026-Q3.md` — veredicto del spike de almacenamiento (PR4b gate).
- `tests/test_log_safe_redaction.py` — átomos de la lista de redacción.
- `AGENTS.md` §18 — exclusión mutua web ↔ legacy y sincronización obligatoria.