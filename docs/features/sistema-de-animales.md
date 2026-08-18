# Sistema de animales — schema

> Feature fundacional del dominio. Esta es la tabla que representa al
> animal en la aplicación. Todas las features de producto (entradas,
> acogidas, adopciones, salud, terapias, contratos, informes) referencian
> a un animal por su `id` o por su `NCHIP`. Sin esta tabla, el resto
> del dominio no puede existir.

> **Slice actual:** schema unicamente (LIFECYCLE-SCHEMA-01). El CRUD
> (LIFECYCLE-SERVICE-01..05, LIFECYCLE-ROUTE-01..06, LIFECYCLE-UI-01)
> viene en ciclos siguientes. Este doc cubre lo que ya está mergeado.

> **Estado de paridad con el legacy (criterio de aceptación duro):**
> este slice **no** ofrece aun la misma funcionalidad que el legacy.
> El legacy permite crear, ver, editar, buscar y listar animales desde
> el formulario `TbFichaAnimal` en el Access. Este slice solo crea la
> tabla; la paridad se alcanza cuando aterricen LIFECYCLE-SERVICE-01..05
> + LIFECYCLE-ROUTE-01..06 + LIFECYCLE-UI-01. La feature "LIFECYCLE-01
> Animal Master CRUD" sera el primer feature que cumpla el criterio
> de paridad. La seccion 2 (criterios de aceptación) explicita esto
> para que cualquier IA o humano que lea este doc entienda exactamente
> que falta.

> **Progreso del feature LIFECYCLE-01 (paridad con el legacy):**
> ✅ **PARIDAD alcanzada** (cierre de issues #31, #67, #70-#72, #75-#81
> en commit 491bfa9). El usuario puede:
> - **Listar** animales activos (`GET /animales`).
> - **Ver el formulario de alta** (`GET /animales/new`).
> - **Crear** un animal (`POST /animales`).
> - **Ver el detalle** de un animal (`GET /animales/{id}`).
> - **Editar** un animal (`GET /animales/{id}/edit` + `POST /animales/{id}/update`).
> - **Borrar** un animal con soft-delete (`POST /animales/{id}/delete`).
>
> Esto cubre las mismas operaciones que el formulario `TbFichaAnimal`
> del Access legacy. Las features que faltan para paridad total con el
> legacy son las que el legacy hace y la web todavia no:
> - **Busqueda** por campos (LIFECYCLE-05: chip, nombre, especie, etc.).
> - **Timeline de eventos** del ciclo de vida (LIFECYCLE-02 + LIFECYCLE-03).
> - **Estado derivado** automatico (LIFECYCLE-03) en vez de calculado
>   a mano.
> - **Cambio de chip** con cascade a registros vinculados (LIFECYCLE-04).
> - **Foto del animal** subida a storage (no incluida en este slice).

## 1. Alcance

Esta feature cubre la definición del schema SQL de la tabla `animales`
en InsForge, su creación idempotente en el startup de la app, y el
contrato de la función de bootstrap.

**Incluye:**

- Definición SQL de la tabla `animales` con 28 columnas (24 del
  legacy `TbFichaAnimal` + 4 mejoras justificadas: `id` UUID PK,
  `fecha_alta`, `updated_at`, `activo`).
- Función `ensure_domain_schema(client)` en `app/core/domain.py`
  que crea la tabla si no existe.
- Cableado en el lifespan de la app (`app/main.py::lifespan`) que
  llama a `ensure_domain_schema` junto a `ensure_schema_and_seed`
  durante el startup.

**No incluye** (queda fuera de este slice, en otros issues):

- El CRUD de animales (create, read, update, soft-delete) — eso es
  LIFECYCLE-SERVICE-01..05 + LIFECYCLE-ROUTE-01..06 + LIFECYCLE-UI-01.
- El timeline de eventos del ciclo de vida — LIFECYCLE-SCHEMA-02
  (tabla `eventos_ciclo_vida_animal`).
- El cache materializado del estado actual — LIFECYCLE-SCHEMA-03
  (tabla `estado_actual_animal`).
- La migracion de datos desde el Access legacy — ciclo separado
  (scripts `migrate_animales.py` etc. que se mencionan en
  `docs/plan-completo.md`).

## 2. Criterios de aceptación

- La tabla `animales` existe en el InsForge de produccion con el
  schema definido en `app/core/domain.py::ANIMALS_CREATE_TABLE_SQL`.
- Las 24 columnas del legacy `TbFichaAnimal` (inspeccionadas via
  Dysflow contra
  `C:\00repos\codigo\APAP_ACTUAL\Registro_APAP_Alcala_datos_18.accdb`)
  tienen destino 1:1 en la tabla nueva. **Cero perdida de campos.**
- Los nombres de columna son los del legacy en CamelCase Spanish
  (NCHIP, NombreAnimal, FIMPLANTACIONCHIP, FNacimiento, FDefuncion,
  Color, Pelo, Tamano, Caracter, Terapia, Eutanasia, RazaPPP,
  Mestizo, EutanasiaOtrasCausas, EutanasiaEnfermedad,
  ComunicacionARIAC, etc.).
- La columna legacy `Situacion` no existe en el schema nuevo. Es
  derivada del event log (LIFECYCLE-SCHEMA-02), no almacenada.
- La columna `NCHIP` es UNIQUE NOT NULL. <!-- alantyle-ignore:ALAN003 -->
- `Especie` esta restringida a `('CANINA', 'FELINA')` via CHECK.
- `Sexo` esta restringido a `('M', 'H')` via CHECK.
- `FNacimiento` es NOT NULL. <!-- alantyle-ignore:ALAN003 -->
- La migracion es idempotente: `CREATE TABLE IF NOT EXISTS` permite <!-- alantyle-ignore:ALAN003 -->
  reiniciar la app sin errores.
- La app arranca con el bootstrap automatico: el lifespan llama a
  `ensure_domain_schema` (junto a `ensure_schema_and_seed`) en cada
  cold start.

## 3. Decisiones de arquitectura

| Decision | Eleccion | Alternativa | Por que |
|---|---|---|---|
| Nombres de columna | CamelCase Spanish exactos del legacy (NCHIP, NombreAnimal) | snake_case English | Consistencia con el resto del schema (TbFichaAnimal del Access). Cero justificacion para renombrar. Decision asentada en issue #29. |
| Primary key | UUID con `gen_random_uuid()` | INT autoincrement | Generacion client-side, no expone orden de creacion, portable entre entornos, suficiente densidad. |
| `NCHIP` como identificador natural | UNIQUE NOT NULL, pero no PK | PK en `NCHIP` | El NCHIP puede ser NULL en animales recien ingresados (pre-implantacion) o cambiarse (LIFECYCLE-04). Un UUID como PK permite esto. | <!-- alantyle-ignore:ALAN003 -->
| `Situacion` legacy | no incluida | Copiada como columna | Es derivada. Se calcula del event log (LIFECYCLE-SCHEMA-02 + LIFECYCLE-03). Tenerla almacenada es un anti-patron (ver `docs/discovery/feature-01-animal-lifecycle.md`). |
| `fecha_alta` (created_at) | TIMESTAMP DEFAULT now() | NULL permitido | Necesario para auditoria y para el orden por defecto en listados. |
| `updated_at` | TIMESTAMP DEFAULT now() | Sin tracking | Necesario para saber cuando cambia un animal. |
| `activo` para soft-delete | BOOLEAN DEFAULT true | DELETE fisico | Preserva FKs historicas. Un animal dado de baja sigue siendo referenciable desde intakes, foster stays, etc. |
| `Color`, `Pelo`, `Tamano`, `Caracter` | TEXT libre | Enum | El legacy los trata como texto libre (valores arbitrarios introducidos por el operario). Mantenemos TEXT. |
| `Terapia`, `Eutanasia`, `RazaPPP`, `Mestizo`, `ComunicacionARIAC` | TEXT (no BOOLEAN) | BOOLEAN | El legacy los trata como texto (`"Si"`/`"No"` en algunos casos, o flags). Mantenemos TEXT para no perder valores intermedios. |
| `FNacimiento` y `FDefuncion` | DATE | TIMESTAMP | Solo se necesita la fecha, no la hora. El legacy usa campos `F+Nombre` para fechas. |
| Indices | Solo los implicitos por UNIQUE y PK | Indices adicionales | Suficiente para el MVP. Indices adicionales se anaden cuando los queries lo justifiquen. |
| DROP+CREATE en prod para renombrar | Directo | ALTER TABLE | Las tablas estaban vacias, no hay perdida. Mas simple que ALTER para 28 columnas. |
| **Validaciones** (en service, no en DB) | En `app/modules/animals/service.py` | Solo en DB | Las validaciones de negocio (nombre no vacio, especie en dominio) viven en el service para devolver errores claros al usuario. La DB solo enforce lo no negociable. |

## 4. Contratos de interfaz

### 4.1 Schema SQL

```sql
CREATE TABLE IF NOT EXISTS animales (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    NCHIP TEXT UNIQUE NOT NULL,
    TraeNChip TEXT,
    FIMPLANTACIONCHIP DATE,
    NombreAnimal TEXT NOT NULL,
    Especie TEXT NOT NULL CHECK (Especie IN ('CANINA', 'FELINA')),
    Sexo TEXT NOT NULL CHECK (Sexo IN ('M', 'H')),
    Raza TEXT,
    Color TEXT,
    Pelo TEXT,
    Tamano TEXT,
    Caracter TEXT,
    FNacimiento DATE NOT NULL,
    FDefuncion DATE,
    Terapia TEXT,
    Observaciones TEXT,
    NombreFoto TEXT,
    Cartilla TEXT,
    Eutanasia TEXT,
    RazaPPP TEXT,
    Mestizo TEXT,
    EutanasiaOtrasCausas TEXT,
    EutanasiaEnfermedad TEXT,
    UltimoEstadoAntesDeFallecido TEXT,
    ComunicacionARIAC TEXT,
    fecha_alta TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    activo BOOLEAN NOT NULL DEFAULT true
)
```

### 4.2 Constante Python

En `app/core/domain.py`:

```python
ANIMALS_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS animales (
    ...
)
"""
```

Es la unica fuente de verdad del schema. Cualquier migracion manual o
herramienta externa debe usar esta constante como referencia.

### 4.3 Funcion de bootstrap

```python
def ensure_domain_schema(client: InsForgeClient) -> None:
    """Create the domain tables (idempotent) in dependency order."""
    client.execute_sql(ANIMALS_CREATE_TABLE_SQL)
    client.execute_sql(VOLUNTARIOS_CREATE_TABLE_SQL)
    client.execute_sql(ROLES_VOLUNTARIO_CREATE_TABLE_SQL)
```

**Orden de creacion**: animales primero (independiente), luego
voluntarios, luego roles_voluntario (FK a voluntarios). Cualquier
orden diferente falla por la FK.

### 4.4 Cableado en el lifespan

En `app/main.py::lifespan`:

```python
@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = config_module.get_settings()
    client = InsForgeClient(settings.insforge_url, settings.insforge_service_key)
    try:
        ensure_schema_and_seed(client, settings)
        ensure_domain_schema(client)
    finally:
        client.close()
    yield
```

El lifespan falla rapido si InsForge no responde. El deploy de
Coolify se marca como rojo y el operador es notificado. Preferimos
eso a arrancar la app y que el primer request 500.

## 5. Modelo de datos

Diagrama de la tabla (por ahora no hay FKs salientes; las FKs
entrantes vendran en otros issues):

```
┌──────────────────────────────────────────────┐
│                 animales                      │
├──────────────────────────────────────────────┤
─ Identidad (mejoras) ────────────────────────
│ id            UUID PK (gen_random_uuid)       │
│ NCHIP         TEXT UNIQUE NOT NULL            │
─ Identidad legacy ───────────────────────────
│ TraeNChip          TEXT                       │
│ FIMPLANTACIONCHIP   DATE                      │
│ NombreAnimal       TEXT NOT NULL              │
│ Especie            TEXT NOT NULL              │
│                    CHECK IN ('CANINA', 'FELINA')│
│ Sexo               TEXT NOT NULL              │
│                    CHECK IN ('M', 'H')         │
─ Caracteristicas fisicas (legacy) ───────────
│ Raza               TEXT                       │
│ Color              TEXT                       │
│ Pelo               TEXT                       │
│ Tamano             TEXT                       │
│ Caracter           TEXT                       │
─ Fechas (legacy) ───────────────────────────
│ FNacimiento        DATE NOT NULL              │
│ FDefuncion         DATE                       │
─ Salud y eutanasia (legacy) ────────────────
│ Terapia            TEXT                       │
│ Eutanasia          TEXT                       │
│ RazaPPP            TEXT                       │
│ Mestizo            TEXT                       │
│ EutanasiaOtrasCausas TEXT                     │
│ EutanasiaEnfermedad   TEXT                     │
│ ComunicacionARIAC    TEXT                     │
─ Documentacion (legacy) ────────────────────
│ Observaciones      TEXT                       │
│ NombreFoto         TEXT                       │
│ Cartilla           TEXT                       │
│ UltimoEstadoAntesDeFallecido TEXT             │
─ Sistema (mejoras) ─────────────────────────
│ fecha_alta         TIMESTAMP NOT NULL          │
│                    DEFAULT now()              │
│ updated_at         TIMESTAMP NOT NULL          │
│                    DEFAULT now()              │
│ activo             BOOLEAN NOT NULL            │
│                    DEFAULT true               │
└──────────────────────────────────────────────┘
```

### Mapeo legacy → nuevo

Todas las 24 columnas del legacy tienen destino 1:1 (mismo nombre).
Las 4 mejoras (`id`, `fecha_alta`, `updated_at`, `activo`) son nuevas
y estan justificadas en la seccion 3.

La columna `Situacion` del legacy se omite a proposito (es
derivada).

## 6. Plan de tests

Cubierto por `tests/test_domain.py` (15 tests del schema) y
`tests/test_animals.py` (12 tests del service layer). Total: 27
tests en esta feature, todos en verde.

### Service layer (12 tests)

- `test_create_animal_ejecuta_insert_con_parametros_esperados` — el
  INSERT contiene los 5 obligatorios en el orden correcto.
- `test_create_animal_rechaza_Especie_invalida_antes_de_sql` — la
  validacion corre antes de tocar la DB.
- `test_create_animal_rechaza_Sexo_invalido_antes_de_sql`
- `test_create_animal_rechaza_NCHIP_vacio`
- `test_create_animal_rechaza_NombreAnimal_vacio`
- `test_create_animal_rechaza_FNacimiento_vacio`
- `test_create_animal_propag_InsForgeError_en_NCHIP_duplicado` — un
  409 de InsForge (NCHIP duplicado) propaga el error tal cual.
- `test_create_animal_acepta_todos_los_campos_opcionales` — el INSERT
  incluye los 24 campos (5 obligatorios + 19 opcionales).
- `test_list_animals_ejecuta_select_y_devuelve_filas` — el SELECT
  filtra por `activo = true` y ordena por `fecha_alta DESC`.
- `test_list_animals_devuelve_lista_vacia_sin_filas`
- `test_get_animal_by_id_devuelve_fila_cuando_existe`
- `test_get_animal_by_id_devuelve_None_si_no_existe`

| Test | Que cubre |
|---|---|
| `test_animales_create_table_sql_uses_if_not_exists` | La SQL usa `IF NOT EXISTS` (idempotente). | <!-- alantyle-ignore:ALAN003 -->
| `test_animales_create_table_sql_has_all_legacy_columns` | Las 24 columnas legacy + 4 mejoras estan presentes. Enumera cada una. |
| `test_animales_table_does_not_store_situacion` | `Situacion` no existe (decision deliberada). |
| `test_animales_table_enforces_especie_and_sexo_domains` | Los CHECK constraints estan en la SQL. |
| `test_animales_NCHIP_is_unique` | `NCHIP TEXT UNIQUE NOT NULL` esta en la SQL. | <!-- alantyle-ignore:ALAN003 -->
| `test_voluntarios_create_table_sql_uses_if_not_exists` | Idem para voluntarios. |
| `test_voluntarios_create_table_sql_has_all_legacy_columns` | Las 4 columnas legacy + 5 mejoras estan presentes. |
| `test_voluntarios_email_and_DNI_are_unique` | Email y DNI son UNIQUE. |
| `test_roles_voluntario_create_table_sql_uses_if_not_exists` | Idem para roles_voluntario. |
| `test_roles_voluntario_references_voluntarios` | La FK a voluntarios esta presente. |
| `test_roles_voluntario_enforces_tipo_rol_domain` | El CHECK en `tipo_rol` esta presente. |
| `test_roles_voluntario_has_unique_voluntario_rol_pair` | El UNIQUE (voluntario_id, tipo_rol) esta presente. |
| `test_ensure_domain_schema_creates_all_three_tables` | La funcion ejecuta los 3 CREATE TABLE. |
| `test_ensure_domain_schema_order_is_animales_then_voluntarios_then_roles` | El orden es el correcto (animales, voluntarios, roles_voluntario). |
| `test_ensure_domain_schema_raises_when_create_table_fails` | Si InsForge devuelve error, la excepcion se propaga. |

**Test E2E (Dysflow contra prod):** se verifica via
`get-table-schema` que las 28 columnas existen en el schema real de
InsForge con los nombres correctos (lowercase por convencion de
Postgres, pero el SQL los mantiene en CamelCase). Verificado el
2026-06-19.

## 7. Historia de migracion

### Origen

El schema es el target de migracion del Access legacy de produccion
(`C:\00repos\codigo\APAP_ACTUAL\Registro_APAP_Alcala_datos_18.accdb`).
La tabla legacy es `TbFichaAnimal` con 26 columnas (25 de datos + el
campo `Situacion` derivado que se omite en el nuevo schema).

### Mapeo

| Legacy `TbFichaAnimal` | Nuevo `animales` | Tipo | Notas |
|---|---|---|---|
| `NCHIP` | `NCHIP` | TEXT UNIQUE NOT NULL | PK natural, identificador de display | <!-- alantyle-ignore:ALAN003 -->
| `TraeNChip` | `TraeNChip` | TEXT | Flag: el animal trae chip al ingreso |
| `FIMPLANTACIONCHIP` | `FIMPLANTACIONCHIP` | DATE | Fecha de implante del chip |
| `NombreAnimal` | `NombreAnimal` | TEXT NOT NULL | | <!-- alantyle-ignore:ALAN003 -->
| `Especie` | `Especie` | TEXT NOT NULL CHECK | CANINA / FELINA | <!-- alantyle-ignore:ALAN003 -->
| `Sexo` | `Sexo` | TEXT NOT NULL CHECK | M / H | <!-- alantyle-ignore:ALAN003 -->
| `Raza` | `Raza` | TEXT | |
| `Color` | `Color` | TEXT | |
| `Pelo` | `Pelo` | TEXT | |
| `Tamaños` (encoding legacy) | `Tamano` | TEXT | Renombrado para corregir encoding |
| `Caracter` | `Caracter` | TEXT | |
| `FNacimiento` | `FNacimiento` | DATE NOT NULL | | <!-- alantyle-ignore:ALAN003 -->
| `FDefuncion` | `FDefuncion` | DATE | |
| `Terapia` | `Terapia` | TEXT | |
| `Observaciones` | `Observaciones` | TEXT | |
| `Situacion` | — | — | REMOVIDO: derivado del event log |
| `NombreFoto` | `NombreFoto` | TEXT | Referencia al nombre del archivo de foto, no al archivo |
| `Cartilla` | `Cartilla` | TEXT | |
| `Eutanasia` | `Eutanasia` | TEXT | |
| `RazaPPP` | `RazaPPP` | TEXT | |
| `Mestizo` | `Mestizo` | TEXT | |
| `EutanasiaOtrasCausas` | `EutanasiaOtrasCausas` | TEXT | |
| `EutanasiaEnfermedad` | `EutanasiaEnfermedad` | TEXT | |
| `UltimoEstadoAntesDeFallecido` | `UltimoEstadoAntesDeFallecido` | TEXT | |
| `ComunicacionARIAC` | `ComunicacionARIAC` | TEXT | |
| — | `id` | UUID PK | Mejora: identificador estable interno |
| — | `fecha_alta` | TIMESTAMP | Mejora: created_at |
| — | `updated_at` | TIMESTAMP | Mejora: tracking de cambios |
| — | `activo` | BOOLEAN | Mejora: soft-delete |

### Coexistencia con el legacy

Durante el periodo de coexistencia (web + Access legacy operando en
paralelo), las altas y modificaciones en la web se replican al
legacy mediante un script de sincronizacion (issue #26 + feature
migracion). La sincronizacion es bidireccional: cualquier cambio en
el legacy se refleja en la web, y viceversa. El script es
responsabilidad de un ciclo futuro (no de este slice).

### DROP+CREATE en produccion

El refactor del 2026-06-19 hizo DROP de las tablas antiguas en
ingles (`animals`, `volunteers`, `volunteer_roles`) y CREATEs de las
nuevas en espanol. Las tablas estaban vacias (recien creadas en el
ciclo #26), por lo que no hubo perdida. El orden fue:

1. `DROP TABLE IF EXISTS roles_voluntario CASCADE;` <!-- alantyle-ignore:ALAN003 -->
   `DROP TABLE IF EXISTS voluntarios CASCADE;` <!-- alantyle-ignore:ALAN003 -->
   `DROP TABLE IF EXISTS animales CASCADE;` <!-- alantyle-ignore:ALAN003 -->
2. `CREATE TABLE animales (...)` con el schema completo.
3. `CREATE TABLE voluntarios (...)`.
4. `CREATE TABLE roles_voluntario (...)`.

## 8. Notas operacionales

### Diagnostico

Para inspeccionar la tabla desde fuera de la app:

```sql
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'animales'
ORDER BY ordinal_position;
```

Para contar animales activos vs inactivos:

```sql
SELECT activo, COUNT(*) FROM animales GROUP BY activo;
```

Para buscar por NCHIP:

```sql
SELECT * FROM animales WHERE NCHIP = '985112004409871';
```

### Mantenimiento

**Cuidado con `DROP TABLE`**: la tabla tiene FKs entrantes en
futuros issues (entradas, foster stays, adopciones, etc.). Si se
necesita recrear, usar `DROP TABLE ... CASCADE` y re-ejecutar la SQL
de `app/core/domain.py::ANIMALS_CREATE_TABLE_SQL`.

**Backups**: la tabla es la fuente de verdad del dominio. Cualquier
cambio de schema debe ir acompanado de un backup previo via `pg_dump`
o equivalente.

**Encoding**: el campo legacy `Tamaños` tenia encoding roto (la `ñ`
se mostraba mal). En el nuevo schema se llama `Tamano` (sin ñ) para
evitar el problema. Si los datos migrados del legacy tienen `Tamaños`
con ñ, el script de migracion debe normalizar a `Tamano` sin ñ.

## 9. Diagramas

(No aplica diagrama de secuencia para este slice: es solo schema. El
diagrama del ciclo de vida del animal esta en la feature de timeline
LIFECYCLE-SCHEMA-02, pendiente.)

## 10. Referencias

- `app/core/domain.py` — SQL constants y funcion `ensure_domain_schema`.
- `app/core/insforge.py` — cliente REST de InsForge.
- `app/main.py::lifespan` — cableado del bootstrap en startup.
- `tests/test_domain.py` — 15 tests del schema.
- `C:\00repos\codigo\APAP_ACTUAL\Registro_APAP_Alcala_datos_18.accdb`
  — backend legacy de produccion (inspeccionable via Dysflow).
- `docs\discovery\feature-01-animal-lifecycle.md` — feature spec del
  legacy (referencia para el diseño del ciclo de vida).
- `docs\discovery\data-model-completeness.md` — reglas de FK,
  constraints, validaciones.
- `docs\architecture\decisiones-proyecto.md` — decisiones de producto sobre el
  dominio.
- Issue #26 — schema inicial (ingles, primera version, reemplazado).
- Issue #29 — verificacion field-by-field contra el Access legacy
  (drive de la decision del refactor).
- Issue #27 — bootstrap en startup.
