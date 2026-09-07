[← Back to Codebase Guide](../CODEBASE-GUIDE.md)

# Architecture

Esta página posee las reglas §18, §31 y §33 de AGENTS verbatim: la arquitectura hexagonal con slices verticales, la decisión de ubicación de cada slice entre `app/core/` y `app/modules/`, el Protocol como abstracción de cliente, y el modo exclusivo web ↔ legacy con sync obligatoria.

## §33 — Ubicación del slice: `app/core/` vs `app/modules/<slice>/`

La arquitectura es **hexagonal con slices verticales** (épica #420). Esta regla responde la única pregunta que surge cada vez que se escribe un slice: **¿dónde va?** Resolverlo mal repetidamente lleva a un monolito por capas con una fachada hexagonal.

### 33.1 Las dos ubicaciones

- **`app/core/<layer>/<slice>/`** — capacidad transversal. Hoy: `auth-users` (#414), `catalogos` (#415), `schema-bootstrap` (#416). Los layers son carpetas globales (`domain/`, `ports/`, `application/`, `adapters/local-backend/`, `di/`) y el slice es un subdirectorio dentro de cada uno.
- **`app/modules/<slice>/`** — capacidad de negocio. El slice posee toda su pila en **una** carpeta.

### 33.2 La regla que decide

Aplique en orden:

1. ¿La consumen **dos o más** slices, **y** no tiene razón de negocio propia para cambiar? → `app/core/`.
2. ¿Posee vocabulario de negocio y cambia por su propia razón? → `app/modules/<slice>/`.
3. **En duda, módulo.** Promover a `core` después es barato. Sacar algo de `core` cuando cinco consumidores dependen de ello, no.

El criterio 1 requiere **ambas** mitades. "Se siente fundacional" no es razón. "Auth ya está ahí" no es razón. Un solo consumidor nunca es suficiente.

### 33.3 Layout de un slice de módulo

```text
app/modules/<slice>/
├── domain/                          # entidades puras y reglas, sin I/O
├── ports/<slice>_port.py            # Protocol: lo que el use case necesita
├── application/                     # un use case por archivo
├── adapters/local-backend/
│   ├── <slice>_local_backend_adapter.py  # implementa el port
│   └── <slice>_local_backend_queries.py  # el SQL vive aquí (ver [code-quality-rules.md](code-quality-rules.md) §22)
├── di/<slice>_di.py                 # composition root del slice
└── routes.py                        # delgado: parsea, delega, renderiza (ver [module-size-budgets.md](module-size-budgets.md) §28)
```

### 33.4 Lo que se sostiene en cualquiera de las dos ubicaciones

- `LocalPostgresExecutor` se construye en composition roots. `domain/`, `ports/` y `application/` dependen de `Protocol` y permanecen ajenos a `psycopg` (§31 es la forma general).
- No se crean `service.py` nuevos que ejecuten SQL. Esa es la capa que este refactor retira; §1 y §5 la describen porque sigue presente en módulos no convertidos, no porque código nuevo deba parecérseles.
- Los criterios de aceptación nombran la **capacidad** (almacenar un archivo, enviar una notificación), nunca el vendor que la provee.
- Cada slice envía un test pin arquitectónico que falla cuando un import de transporte se filtra a la capa equivocada. Una regla sin gate es [anti-patterns.md](anti-patterns.md) §32.P3.

### 33.5 Excepción conocida, registrada a propósito

`app/core/application/admin/` lo consumen solo `app/core/admin_handlers.py` y `app/main.py` — ningún segundo slice. Por §33.2 pertenece a `app/modules/`. Aterrizó en `core` porque se convirtió pronto (#419), no porque sea transversal.

**No** se está moviendo: reubicar un slice recién mergeado es churn sin ganancia funcional. Se registra aquí para que se lea como una excepción deliberada y no como precedente. No cite `admin` para justificar poner la próxima capacidad de negocio en `core`.

**Aplicación**: revisión de PR contra §33.2, más los pin tests por slice de §33.4. El índice de slices, orden de ejecución y definición de hecho viven en el issue #420.

## §18 — Aislamiento web ↔ legacy + sync obligatoria (nivel proyecto)

APAP_WEB sirve requests contra PostgreSQL. El legacy Access/VBA participa como origen o destino solo durante operaciones explícitas del paquete `migration/`.

| Modo | Backend | Ruta de código |
|---|---|---|
| **Web** | PostgreSQL | `app/main.py` → `app/core/local_backend/db.py::LocalPostgresExecutor` |
| **Legacy** | Archivo `.accdb` de Access | Adapters bajo `migration/` durante apply o reconcile |

No existe un selector de backend de datos en `Settings`. Su campo `mode` distingue `web` y `test` para middleware; la coordinación entre PostgreSQL y Access pertenece al CLI de migración.

### 18.1 Función de sync obligatoria (HARD) <!-- alantyle-ignore:ALAN003 -->

Ambos modos escriben a sus backends respectivos de forma independiente. No hay estado vivo compartido. Para mover datos entre ellos, el proyecto envía una función de sync bidireccional obligatoria (por directiva del usuario del 2026-07-05):

- Vive en el paquete `migration/` (engine + CLI).
- La dirección es configurable: `legacy → web`, `web → legacy` o `bidirectional` con last-write-wins / merge-by-natural-key.
- La sync debe ser **idempotente**: re-ejecutar sin cambios no produce diff. La implementación usa la tabla `web_only_feature_shadow` (o equivalente) para rastrear la divergencia entre los dos backends y solo escribe las filas que efectivamente difieren.
- La sync debe ser **auditable**: cada fila escrita se loguea vía `log_safe("sync.applied", table, pk, direction, source_hash, target_hash)` (ver [logging-conventions.md](logging-conventions.md)).
- La sync debe ser **segura ante mutación concurrente**: el engine sostiene un advisory lock (basado en archivo o DB-level) para que dos operadores no ejecuten syncs en conflicto simultáneamente.

### 18.2 CLI de superficie (ya existe)

El CLI de sync es `python -m migration reconcile` (ver `migration/cli.py`):

```bash
# Read-only: enumera divergencias sin escribir
python -m migration reconcile --check-only

# Recorre divergencias interactivamente
python -m migration reconcile --interactive

# Filtra a una tabla
python -m migration reconcile --table voluntarios

# Filtra por timestamp de divergencia
python -m migration reconcile --since 2026-06-20T00:00:00+00:00
```

El CLI envía `apap-migrate reconcile <flags>` como punto de entrada.

### 18.3 Modos de fallo (HARD REJECT) <!-- alantyle-ignore:ALAN003 -->

- ❌ Rutas de código que leen ambos backends en el mismo request. Elija uno por request.
- ❌ Rutas de código que escriben a un modo mientras leen del otro. Elija uno por request.
- ❌ Rutas web que importan adapters de Access o el paquete `migration/`.
- ❌ Runs de sync que no comprueben idempotencia antes de aplicar. Use el diff engine.
- ❌ Runs de sync sin auditoría `log_safe`. Cada fila escrita se loguea.

### 18.4 Aplicación

El aislamiento y la función de sync se aplican en tres capas:

1. **Settings** (`app/core/config.py`) aporta `APAP_LOCAL_DB_URL` y el esquema opcional.
2. **`LocalPostgresExecutor`** implementa `SqlExecutor`; services y casos de uso dependen del contrato, no de `psycopg`.
3. **`migration/`** es el único paquete permitido para coordinar PostgreSQL y Access. Routes y services no deben importarlo.

**Aplicación**: revisión de imports y `scripts/check_migration_boundaries.py`.

## §31 — Los services de dominio dependen de abstracciones Protocol

Los services de dominio deben depender de abstracciones Protocol, nunca de clientes backend concretos. `app.core.data_access.SqlExecutor` es el precedente. Ejemplo: `def list_items(client: SqlExecutor) -> list[Item]: ...`.

§33 es la forma con forma de slice de esta regla: el Protocol es el port propio del slice en `ports/<slice>_port.py`, expresado en términos de dominio más que como un ejecutor SQL genérico.

## Core invariants

- **Hexagonal como target**: el layout `app/core/<layer>/<slice>/` cumple §33.3; los `service.py` planos en `app/modules/` son deuda en conversión, no patrón a imitar.
- **Una ubicación por slice**: dos consumidores y sin razón propia → `core`; razón de negocio propia → `modules/`. En duda, módulo.
- **Runtime web único**: los requests usan PostgreSQL; Access queda fuera de la aplicación web.
- **Sync idempotente + auditable + lockable**: cada fila escrita se loguea y la sync puede re-ejecutarse sin daño.
- **Protocol como abstracción**: ninguna firma de service de dominio depende de `LocalPostgresExecutor` directamente.

## Contributor checklist

- [ ] Antes de crear un slice, aplicó §33.2 y justificó la ubicación en el PR.
- [ ] Cada nuevo slice convertido incluye `domain/`, `ports/`, `application/`, `adapters/local-backend/`, `di/` y un pin test de capas.
- [ ] Ningún slice nuevo introduce SQL fuera de `adapters/local-backend/<slice>_local_backend_queries.py`.
- [ ] Las funciones de service de dominio reciben `Protocol` o `SqlExecutor`, no `LocalPostgresExecutor`.
- [ ] Si toca el sync, leyó `migration/cli.py` y respeta §18.3.

## Navigation

Previous: [CodeGraph conventions](codegraph-conventions.md) | Next: [Security](security.md)
