# Arquitectura actual de LocalBackend

[Volver a la guía del código](../CODEBASE-GUIDE.md)

Esta página describe la arquitectura LocalBackend que existe en el código actual. No define el modelo de dominio ni sustituye los runbooks de despliegue y migración.

## Ruta rápida

1. Abra `app/main.py` para la composición del servicio web desplegado.
2. Abra `app/core/local_backend/db.py` para el límite de PostgreSQL.
3. Abra `app/core/local_backend/app.py` solo para la API de compatibilidad y sus pruebas.
4. Abra `migration/adapters/local_backend/` para el acceso del proceso de migración.

## Decisión vigente

El servicio web accede directamente a PostgreSQL mediante `LocalPostgresExecutor`. No existe un `LocalBackendClient` HTTP en el runtime actual.

La API de `app/core/local_backend/app.py` es una aplicación FastAPI separada. Conserva contratos de integración, pero no está montada en `app.main` ni es el proceso iniciado por el `Dockerfile`.

## Modelo mental

```text
navegador
   |
   v
app.main:app  -- routes, middleware, HTML
   |
   v
SqlExecutor (Protocol)
   |
   v
LocalPostgresExecutor -- psycopg, una conexión por ejecución
   |
   v
PostgreSQL

migration use cases -> SqlExecutor Protocol
adapter disponible -> LocalPostgresExecutor (sin wiring CLI)

pruebas y verificadores de fallback -> local_backend.app:create_app
```

## Composición del servicio web

| Responsabilidad | Evidencia vigente |
|---|---|
| Proceso desplegado | `Dockerfile` inicia `uvicorn app.main:app` en el puerto 8000. |
| Composition root | `app/main.py::lifespan` crea `LocalPostgresExecutor` y lo guarda en `app.state.sql_executor`. |
| Configuración de datos | `app/core/config.py::Settings` lee `APAP_LOCAL_DB_URL` y `APAP_LOCAL_DB_SCHEMA`. |
| Arranque | `app/main.py::lifespan` ejecuta el bootstrap de auth, catálogos, dominio y migraciones SQL antes de servir tráfico. |
| Inyección en requests | `app/core/di/auth_dependencies_session_di.py::get_local_backend_client_dep` entrega el `SqlExecutor` de `app.state`. |
| Registro HTTP | `app/main.py::create_app` instala middleware, auth, administración y routers de dominio. |

El arranque propaga cualquier fallo del bootstrap. Así evita aceptar requests con una base de datos inaccesible o un esquema incompleto.

## Límite de base de datos

`app/core/data_access.py::SqlExecutor` define la superficie mínima `execute_sql(query, params)`. Services, casos de uso y migración dependen de ese contrato estructural.

`app/core/local_backend/db.py::LocalPostgresExecutor` implementa el contrato con `psycopg`. Abre una conexión por ejecución y aplica el `search_path` en cada conexión cuando se configura.

El ejecutor traduce errores SQL con estado de PostgreSQL a `QueryError`. Traduce fallos de conexión a `DatabaseError` y devuelve las filas como diccionarios.

El SQL de negocio sigue perteneciendo a cada slice. Consulte [Capas y slices](../codebase/architecture.md) para la ubicación de queries, ports, adapters y casos de uso.

## Límites de autenticación y sesión

| Límite | Evidencia vigente |
|---|---|
| Identidad de sesión | `app/core/session.py` firma y lee la cookie `apap_session` con `APAP_SESSION_SECRET`. |
| Autorización | `app/core/di/auth_dependencies_session_di.py::require_authorized_user` revalida el email contra `usuarios_autorizados`. |
| Caché | `app/core/auth_cache.py` conserva decisiones positivas y negativas en proceso durante el TTL configurado. |
| Fuente de verdad | La fila activa de `usuarios_autorizados`, consultada mediante `SqlExecutor`, decide el acceso. |
| OAuth del servicio web | `app/core/auth_flow.py` traduce cookies y redirects y delega las decisiones a `app/core/application/oauth/`. |

Una sesión firmada no basta para autorizar. Si falta la sesión, el flag es restrictivo, la base no responde o el usuario ya no está activo, la dependencia deniega el acceso.

## Límite de storage

El servicio web persiste objetos (fotos) en MinIO (S3-compatible). La
cliente `minio` de Python se conecta a `APAP_S3_ENDPOINT` con
`APAP_S3_ACCESS_KEY` y `APAP_S3_SECRET_KEY`.

`app/core/local_backend/s3.py` expone el cliente MinIO y lo conecta al
lifespan de `app/main` como `app.state.minio_client`. Los adapters de
storage lo consumen via el protocolo `PhotoStorageClient`.

`app/core/local_backend/storage.py` (la API de compatibilidad) usa el
mismo cliente MinIO para las rutas `GET /api/storage/buckets` y
`POST /api/storage/buckets`. El stub in-memory fue eliminado en M0
(issue #641).

El bucket se auto-crea en el arranque si no existe
(`APAP_S3_BUCKET`). Sin credenciales de MinIO el servicio arranca
normalmente pero la descarga de fotos devuelve el placeholder 1x1 PNG.

## API de compatibilidad LocalBackend

`app/core/local_backend/app.py::create_app` construye una segunda aplicación FastAPI con lifespan independiente.

| Ruta | Responsabilidad actual | Implementación |
|---|---|---|
| `GET /healthz` | Devuelve el sobre de salud de compatibilidad. | `app/core/local_backend/healthz.py` |
| `POST /api/database/advance/rawsql` | Ejecuta SQL y conserva el sobre `rows`/`rowCount`. | `app/core/local_backend/rawsql.py` |
| `GET/POST /api/storage/buckets` | Lista o crea buckets via MinIO. | `app/core/local_backend/storage.py` |
| `/api/auth/oauth/*` | Devuelve respuestas OAuth simuladas; no contacta con Google. | `app/core/local_backend/oauth_google.py` |
| `POST /api/magic/start` | Persiste un token y solicita su envío por SMTP si está configurado. | `app/core/local_backend/magic_link.py` |
| `GET /api/magic/verify` | Consume el token y emite la cookie de sesión o redirige al login. | `app/core/local_backend/magic_link.py` |

Las pruebas de integración crean esta aplicación mediante su factory. Los verificadores de fallback también pueden iniciarla en un subproceso si reciben `APAP_LOCAL_DB_URL`.

## Integración con migración

`migration/adapters/local_backend/migration_local_backend_adapter.py::build_migration_executor` puede crear el mismo `LocalPostgresExecutor` usado por el servicio web.

`LocalBackendMigrationAdapter` es un pass-through de `execute_sql`. Sin embargo, ningún módulo lo instancia actualmente y la factory no tiene callers.

`migration/cli.py::main` deja `web_client` en `None` si el caller no lo inyecta. Por tanto, apply y reconcile no componen todavía el adapter PostgreSQL desde la línea de comandos.

Los flujos legacy → web, web → legacy y reconcile viven en `migration/`. Consulte [Sync and cloud](../codebase/sync-and-cloud.md) para sus reglas operativas.

## Configuración relevante

| Variable | Consumidor | Comportamiento actual |
|---|---|---|
| `APAP_LOCAL_DB_URL` | `app/main.py`, `app/core/local_backend/app.py` | DSN de PostgreSQL. La API separada falla de forma explícita si falta. El CLI de migración aún no lo consume. |
| `APAP_LOCAL_DB_SCHEMA` | Ambos lifespans | `search_path` opcional; vacío conserva el esquema por defecto de PostgreSQL. |
| `APAP_SESSION_SECRET` | Servicio web y API separada | Firma sesiones; el servicio web lo valida al arrancar fuera de debug. |
| `APAP_AUTH_CACHE_TTL_SECONDS` | Dependencias de autorización | Ventana del caché de autorización en proceso. |
| `APAP_SMTP_*` | API separada de magic-link | Configura `SMTPMailTransport`; sin host, el envío es no-op. |
| `APAP_PUBLIC_BASE_URL` | API separada de magic-link | Base del enlace de verificación; por defecto, `http://127.0.0.1:8000`. |

| `APAP_S3_ENDPOINT`, `APAP_S3_ACCESS_KEY`, `APAP_S3_SECRET_KEY`, `APAP_S3_BUCKET` | Lifespan, `s3.py` | Cliente MinIO; sin credenciales el servicio arranca con fallback placeholder para fotos. |
`Settings` no selecciona entre un backend HTTP y PostgreSQL. Su campo `mode` distingue `web` y `test` para middleware; no representa un modo Access de datos.

## Invariantes principales

- **PostgreSQL directo**: el servicio web llega a datos mediante `SqlExecutor` y `LocalPostgresExecutor`, no mediante un cliente HTTP.
- **Un composition root por aplicación**: `app.main` y la API separada poseen lifespans y claves de `app.state` distintas.
- **Fail-fast de esquema**: el servicio web completa el bootstrap antes de aceptar tráfico.
- **Autorización revalidada**: la cookie aporta identidad; `usuarios_autorizados` conserva la decisión de acceso.
- **Storage real en MinIO**: fotos van a MinIO via `app/core/local_backend/s3.py`.
- **Migración aislada**: solo `migration/` coordina PostgreSQL y Access; su composición CLI permanece incompleta.

## Checklist del contribuidor

- [ ] Confirme en `Dockerfile` qué aplicación se despliega antes de documentar una ruta.
- [ ] Mantenga los consumidores de datos detrás de `SqlExecutor` o del port específico del slice.
- [ ] No describa la API separada como montada en `app.main` sin wiring y pruebas que lo demuestren.
- [ ] Actualice la sección storage cuando MinIO deje de ser stub.
- [ ] Actualice esta página cuando cambien los lifespans, el ejecutor, auth, storage o el adapter de migración.
- [ ] Verifique que cada ruta y enlace Markdown resuelve dentro del repositorio.

## Navegación

Anterior: [Referencia técnica](../../DOCS.md) | Siguiente: [Decisiones de proyecto](decisiones-proyecto.md)
