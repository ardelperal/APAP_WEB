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
> este slice **NO** ofrece aun la misma funcionalidad que el legacy.
> El legacy permite crear, ver, editar, buscar y listar animales desde
> el formulario `TbFichaAnimal` en el Access. Este slice solo crea la
> tabla; la paridad se alcanza cuando aterricen LIFECYCLE-SERVICE-01..05
> + LIFECYCLE-ROUTE-01..06 + LIFECYCLE-UI-01. La feature "LIFECYCLE-01
> Animal Master CRUD" sera el primer feature que cumpla el criterio
> de paridad. La seccion 2 (criterios de aceptación) explicita esto
> para que cualquier IA o humano que lea este doc entienda exactamente
> que falta.

> **Progreso del feature LIFECYCLE-01 (paridad con el legacy):**
> ✅ **PARIDAD ALCANZADA** (cierre de issues #31, #67, #70-#72, #75-#81
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
> - **Timeline de eventos** del ciclo de vida (LIFECYCLE-02 + LIFECYCLE-03):
>   schema slice 1 ya mergeado (eventos_ciclo_vida_animal + estado_actual_animal),
>   falta el slice 2 (service layer que escribe eventos al insertar intakes,
>   fosters, adopciones) y slice 3 (resolver que actualiza el cache desde
>   el log).
> - **Estado derivado** automatico (LIFECYCLE-03) en vez de calculado
>   a mano. El cache esta listo (estado_actual_animal) pero el resolver
>   no esta implementado.
> - **Cambio de chip** con cascade a registros vinculados (LIFECYCLE-04).
> - **Foto del animal** subida a storage (no incluida en este slice).

## 1. Alcance

Esta feature cubre la definición del schema SQL del dominio de animales
en InsForge, su creación idempotente en el startup de la app, y el
contrato de la función de bootstrap. Cubre el schema fundacional
(`animales`), el registro de voluntarios y sus roles
(`voluntarios` + `roles_voluntario`) y, desde LIFECYCLE-02, el log de
eventos del ciclo de vida y el cache del estado actual.

**Incluye:**

- Definición SQL de la tabla `animales` con 28 columnas (24 del
  legacy `TbFichaAnimal` + 4 mejoras justificadas: `id` UUID PK,
  `fecha_alta`, `updated_at`, `activo`).
- Definición SQL de las tablas de voluntarios y sus roles
  (`voluntarios`, `roles_voluntario`).
- Definición SQL del **log de eventos del ciclo de vida**
  (`eventos_ciclo_vida_animal`, 13 columnas, snake_case espanol) — es
  el append-only log de las transiciones del animal (intake, foster,
  adoption, death, etc.). Su fuente de verdad del estado.
- Definición SQL del **cache materializado del estado actual**
  (`estado_actual_animal`, 10 columnas, snake_case espanol) — una fila
  por animal con el estado DameSituacion actual y punteros al evento
  activo que lo causo. Se reconstruye desde eventos_ciclo_vida_animal.
- Funcion `ensure_domain_schema(client)` en `app/core/domain.py`
  que crea las 5 tablas + 6 indices en orden de dependencia FK.
- Cableado en el lifespan de la app (`app/main.py::lifespan`) que
  llama a `ensure_domain_schema` junto a `ensure_schema_and_seed`
  durante el startup.

**No incluye** (queda fuera de este slice, en otros issues):

- El CRUD de animales (create, read, update, soft-delete) — eso es
  LIFECYCLE-SERVICE-01..05 + LIFECYCLE-ROUTE-01..06 + LIFECYCLE-UI-01.
- **Slice 2 de LIFECYCLE-02**: el service layer que escribe eventos
  automaticamente al insertar intakes/fosters/adoptions/deaths. El
  schema esta listo (este slice), pero `INSERT INTO
  eventos_ciclo_vida_animal` no se ejecuta todavia desde la aplicacion.
- **Slice 3 de LIFECYCLE-02**: el resolver que reconstruye
  `estado_actual_animal` desde el log. El cache esta listo (este slice),
  pero el codigo que lo mantiene sincronizado no esta implementado.
- La UI del timeline (LIFECYCLE-UI-02) y la UI de estado en la ficha
  del animal (LIFECYCLE-UI-03).
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
- La columna legacy `Situacion` NO existe en el schema nuevo. Es
  derivada del event log (LIFECYCLE-SCHEMA-02), no almacenada.
- La columna `NCHIP` es UNIQUE NOT NULL.
- `Especie` esta restringida a `('CANINA', 'FELINA')` via CHECK.
- `Sexo` esta restringido a `('M', 'H')` via CHECK.
- `FNacimiento` es NOT NULL.
- La migracion es idempotente: `CREATE TABLE IF NOT EXISTS` permite
  reiniciar la app sin errores.
- La app arranca con el bootstrap automatico: el lifespan llama a
  `ensure_domain_schema` (junto a `ensure_schema_and_seed`) en cada
  cold start.

## 3. Decisiones de arquitectura

| Decision | Eleccion | Alternativa | Por que |
|---|---|---|---|
| Nombres de columna | CamelCase Spanish exactos del legacy (NCHIP, NombreAnimal) | snake_case English | Consistencia con el resto del schema (TbFichaAnimal del Access). Cero justificacion para renombrar. Decision asentada en issue #29. |
| Primary key | UUID con `gen_random_uuid()` | INT autoincrement | Generacion client-side, no expone orden de creacion, portable entre entornos, suficiente densidad. |
| `NCHIP` como identificador natural | UNIQUE NOT NULL, pero no PK | PK en `NCHIP` | El NCHIP puede ser NULL en animales recien ingresados (pre-implantacion) o cambiarse (LIFECYCLE-04). Un UUID como PK permite esto. |
| `Situacion` legacy | NO incluida | Copiada como columna | Es derivada. Se calcula del event log (LIFECYCLE-SCHEMA-02 + LIFECYCLE-03). Tenerla almacenada es un anti-patron (ver `docs/discovery/feature-01-animal-lifecycle.md`). |
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
    # 5 tablas en orden de dependencia FK
    client.execute_sql(ANIMALS_CREATE_TABLE_SQL)
    client.execute_sql(VOLUNTARIOS_CREATE_TABLE_SQL)
    client.execute_sql(ROLES_VOLUNTARIO_CREATE_TABLE_SQL)
    client.execute_sql(EVENTOS_CICLO_VIDA_ANIMAL_CREATE_TABLE_SQL)
    client.execute_sql(ESTADO_ACTUAL_ANIMAL_CREATE_TABLE_SQL)

    # 6 indices (cada uno en su propia constante defensivamente)
    client.execute_sql(EVENTOS_CICLO_VIDA_ANIMAL_IDX_ANIMAL_FECHA)
    client.execute_sql(EVENTOS_CICLO_VIDA_ANIMAL_IDX_TIPO)
    client.execute_sql(EVENTOS_CICLO_VIDA_ANIMAL_IDX_LEGACY)
    client.execute_sql(EVENTOS_CICLO_VIDA_ANIMAL_IDX_CAUSA)
    client.execute_sql(ESTADO_ACTUAL_ANIMAL_IDX_SITUACION)
    client.execute_sql(ESTADO_ACTUAL_ANIMAL_IDX_RECONCILIACION)
```

**Orden de creacion** (11 calls totales: 5 CREATE TABLE + 6 CREATE INDEX):

1. `animales` — independiente, tabla mas escrita.
2. `voluntarios` — independiente de animales.
3. `roles_voluntario` — FK a voluntarios.
4. `eventos_ciclo_vida_animal` — FK a animales + self, necesita animales
   ya creada.
5. `estado_actual_animal` — FK a animales + eventos_ciclo_vida_animal,
   necesita ambas creadas.
6-11. Los 6 indices (CREATE INDEX IF NOT EXISTS, idempotente).

Cualquier reorden que rompa las FKs falla con `relation "X" does not
exist` en una base limpia. La idempotencia viene de `CREATE TABLE IF
NOT EXISTS` y `CREATE INDEX IF NOT EXISTS`: se puede ejecutar N veces
sin efecto colateral.

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

### eventos_ciclo_vida_animal (issue #68)

Log append-only del ciclo de vida del animal. Es la fuente de verdad del
estado: `estado_actual_animal` es solo un cache que se reconstruye
desde aqui. 13 columnas (todas snake_case espanol — esta tabla NO
existe en el legacy, es invencion del log web, por lo tanto no hay
columnas heredadas en CamelCase).

```
┌─────────────────────────────────────────────────────────────┐
│               eventos_ciclo_vida_animal                     │
├─────────────────────────────────────────────────────────────┤
─ Identidad ──────────────────────────────────────────────────
│ id                UUID PK (gen_random_uuid)                 │
─ Transicion ─────────────────────────────────────────────────
│ animal_id         UUID NOT NULL FK -> animales(id)         │
│ tipo_evento       VARCHAR(50) NOT NULL                     │
│                    CHECK IN (13 valores del catalogo)       │
│ fecha_evento      TIMESTAMPTZ NOT NULL                     │
─ Cadena causal (eventos sinteticos) ─────────────────────────
│ evento_causa_id   UUID FK -> eventos_ciclo_vida_animal(id)  │
│                    NULLABLE (solo eventos sinteticos)       │
─ Trazabilidad legacy ───────────────────────────────────────
│ tabla_origen_legacy  VARCHAR(50)                           │
│                    'TbEntradas'|'TbAcogidaAnimal'|         │
│                    'TbAdopcion'|'TbFichaAnimal'            │
│ id_origen_legacy    INTEGER                                │
│                    IDEntrada|IDAcogida|IDAdopcion|etc.     │
─ Referencia web (futuro) ───────────────────────────────────
│ fuente_entidad_tipo VARCHAR(30)                            │
│                    'intake'|'foster'|'adoption'|'death'    │
│ fuente_entidad_id   UUID                                   │
─ Metadata libre ────────────────────────────────────────────
│ metadatos          JSONB                                   │
│                    {causa_muerte, razon_devolucion, etc.}   │
─ Auditoria ─────────────────────────────────────────────────
│ creado_por         UUID NOT NULL FK ->                     │
│                    usuarios_autorizados(id)                │
│ fecha_creacion     TIMESTAMP NOT NULL DEFAULT now()        │
─ Sistema ───────────────────────────────────────────────────
│ activo             BOOLEAN NOT NULL DEFAULT true           │
└─────────────────────────────────────────────────────────────┘
```

**Catalogo `tipo_evento`** (13 strings, snake_case en ingles porque son
invencion del log web y no existe contraparte legacy que mantener):

| Evento | Tabla legacy | Transicion |
|---|---|---|
| `INTAKE_STARTED` | `TbEntradas` INSERT | Entra al albergue |
| `INTAKE_COMPLETED` | `TbEntradas.FSalida` SET | Salio del albergue sin retorno a dueno |
| `INTAKE_REOPENED` | `TbEntradas.FSalida` SET NULL | Re-abre intake |
| `FOSTER_STARTED` | `TbAcogidaAnimal` INSERT | Entra en acogida |
| `FOSTER_CLOSED_BY_ADOPTION` | `TbAcogidaAnimal.FFinal` SET | Acogida cerrada por adopcion |
| `FOSTER_RETURNED` | `TbAcogidaAnimal.FFinal` SET | Acogida cerrada por devolucion |
| `FOSTER_REOPENED` | `TbAcogidaAnimal.FFinal` SET NULL | Re-abre acogida |
| `ADOPTION_STARTED` | `TbAdopcion` INSERT | Entra en adopcion |
| `ADOPTION_RETURNED` | `TbAdopcion.FDevolucion` SET | Adopcion devuelta |
| `ADOPTION_REOPENED` | `TbAdopcion.FDevolucion` SET NULL | Re-abre adopcion |
| `OWNER_RETURNED` | `TbEntradas.FEntregaAPropietario` SET | Entregado al propietario (terminal) |
| `DEATH_RECORDED` | `TbFichaAnimal.FDefuncion` SET | Muerte (terminal; mass-closes) |
| `STATE_CORRECTION` | manual | Correccion admin |

**Indices** (4):

1. `(animal_id, fecha_evento DESC)` — eventos por animal, mas reciente
   primero. Es el query principal del timeline.
2. `(tipo_evento)` — filtrar por tipo (ej: "todos los INTAKE_STARTED
   del ultimo mes").
3. `(tabla_origen_legacy, id_origen_legacy)` — lookup desde un ID
   legacy (ej: "que evento genero la adopcion con IDAdopcion=123?").
4. `(evento_causa_id)` — trazar cadena causal (ej: "que evento
   sintetico provoco este otro?").

### estado_actual_animal (issue #69)

Cache materializado del estado actual del animal. Una fila por animal
(`animal_id` es PK). Se reconstruye desde `eventos_ciclo_vida_animal`.
10 columnas (snake_case espanol).

```
┌─────────────────────────────────────────────────────────────┐
│               estado_actual_animal                          │
├─────────────────────────────────────────────────────────────┤
─ Identidad ──────────────────────────────────────────────────
│ animal_id         UUID PK FK -> animales(id)               │
─ Estado actual ──────────────────────────────────────────────
│ situacion_actual  VARCHAR(50) NOT NULL                     │
│                    CHECK (7 base + LIKE 'Fallecido (%)')   │
─ Puntero al evento causal ──────────────────────────────────
│ evento_activo_id  UUID FK -> eventos_ciclo_vida_animal(id)  │
│                    NULLABLE (pre-migracion: sin evento)     │
─ Punteros a entidades activas ──────────────────────────────
│ intake_activo_id   UUID (para estado 'Albergue')            │
│ foster_activo_id   UUID (para estado 'Acogida')             │
│ adopcion_activa_id  UUID (para estado 'Adoptado')           │
─ Metadata de transicion ────────────────────────────────────
│ fecha_cambio_estado TIMESTAMPTZ NOT NULL                   │
─ Reconciliacion legacy ────────────────────────────────────
│ situacion_legacy  VARCHAR(100) (legacy DameSituacion)       │
│ estado_reconciliacion VARCHAR(20) NOT NULL                 │
│                    DEFAULT 'pending'                       │
│                    CHECK IN ('pending', 'matched',         │
│                             'divergent', 'migrated')       │
─ Sistema ───────────────────────────────────────────────────
│ activo             BOOLEAN NOT NULL DEFAULT true           │
└─────────────────────────────────────────────────────────────┘
```

**Valores `situacion_actual`** (catalogo DameSituacion):

| Valor | Significado |
|---|---|
| `Pendiente de Entrada` | Antes del primer intake |
| `Pendiente de Nueva Situacion` | Estado transitorio |
| `Albergue` | En el shelter |
| `Acogida` | En casa de acogida |
| `Adoptado` | Adoptado |
| `Entregado` | Devuelto al propietario (terminal) |
| `Incoherente` | Estado inconsistente (requiere atencion admin) |
| `Fallecido (%)` | Fallecido; el `%` se sustituye por el estado previo (Albergue/Acogida/Adoptado/Entregado/Desconocido) |

**Indices** (2):

1. `(situacion_actual)` — dashboard queries (ej: "cuantos animales
   en Acogida?").
2. `(estado_reconciliacion)` — tracking de la migracion legacy → web
   (cuantas filas quedan `pending`, cuantas `matched`/`divergent`/
   `migrated`).

**Decisiones de diseno**:

- **No incluye `estado_previo_muerte`**: el dato ya existe en
  `animales.UltimoEstadoAntesDeFallecido` (CamelCase legacy, ya
  migrado). Duplicar seria redundancia y abre la puerta a drift entre
  dos copias. Cuando se necesita el dato, la query hace JOIN a
  `animales`.
- **`situacion_actual` cubre Fallecido via LIKE**: PostgreSQL permite
  patrones en CHECK. Esto evita enumerar las 5 variantes de Fallecido
  en el catalogo cerrado.

### Convencion de naming

Las columnas heredadas del legacy respetan CamelCase exacto
(`NCHIP`, `NombreAnimal`, `UltimoEstadoAntesDeFallecido`).
Las columnas/mejoras nuevas del web son snake_case espanol coherente
(`id`, `fecha_alta`, `activo`, `animal_id`, `tipo_evento`,
`situacion_actual`). Decision asentada en memoria #13454: las columnas
heredadas son bit-incompatibles para preservar la opcion de migracion
bidireccional legacy↔web en cualquier momento; las nuevas son del web
y no se persiguen en el legacy.

### Mapeo legacy → nuevo

Todas las 24 columnas del legacy tienen destino 1:1 (mismo nombre).
Las 4 mejoras (`id`, `fecha_alta`, `updated_at`, `activo`) son nuevas
y estan justificadas en la seccion 3.

La columna `Situacion` del legacy se omite a proposito (es
derivada).

## 6. Plan de tests

Cubierto por `tests/test_domain.py` (32 tests del schema — 15 del
slice LIFECYCLE-SCHEMA-01 + 17 nuevos del slice LIFECYCLE-02) y
`tests/test_animals.py` (12 tests del service layer). Total: 44 tests
en esta feature, todos en verde.

### Service layer (12 tests)

- `test_create_animal_ejecuta_insert_con_parametros_esperados` — el
  INSERT contiene los 5 obligatorios en el orden correcto.
- `test_create_animal_rechaza_Especie_invalida_antes_de_sql` — la
  validacion corre ANTES de tocar la DB.
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

### Schema — slice LIFECYCLE-SCHEMA-01 (15 tests originales)

| Test | Que cubre |
|---|---|
| `test_animales_create_table_sql_uses_if_not_exists` | La SQL usa `IF NOT EXISTS` (idempotente). |
| `test_animales_create_table_sql_has_all_legacy_columns` | Las 24 columnas legacy + 4 mejoras estan presentes. Enumera cada una. |
| `test_animales_table_does_not_store_situacion` | `Situacion` no existe (decision deliberada). |
| `test_animales_table_enforces_especie_and_sexo_domains` | Los CHECK constraints estan en la SQL. |
| `test_animales_NCHIP_is_unique` | `NCHIP TEXT UNIQUE NOT NULL` esta en la SQL. |
| `test_voluntarios_create_table_sql_uses_if_not_exists` | Idem para voluntarios. |
| `test_voluntarios_create_table_sql_has_all_legacy_columns` | Las 4 columnas legacy + 5 mejoras estan presentes. |
| `test_voluntarios_email_and_DNI_are_unique` | Email y DNI son UNIQUE. |
| `test_roles_voluntario_create_table_sql_uses_if_not_exists` | Idem para roles_voluntario. |
| `test_roles_voluntario_references_voluntarios` | La FK a voluntarios esta presente. |
| `test_roles_voluntario_enforces_tipo_rol_domain` | El CHECK en `tipo_rol` esta presente. |
| `test_roles_voluntario_has_unique_voluntario_rol_pair` | El UNIQUE (voluntario_id, tipo_rol) esta presente. |
| `test_ensure_domain_schema_creates_all_five_tables_and_indexes` | La funcion ejecuta 5 CREATE TABLE + 6 CREATE INDEX = 11 calls. |
| `test_ensure_domain_schema_order_is_animales_then_voluntarios_then_roles` | Las primeras 3 tablas van en orden correcto (animales, voluntarios, roles_voluntario). |
| `test_ensure_domain_schema_raises_when_create_table_fails` | Si InsForge devuelve error, la excepcion se propaga. |

### Schema — slice LIFECYCLE-02 (17 tests nuevos)

| Test | Que cubre |
|---|---|
| `test_eventos_ciclo_vida_animal_create_table_sql_existe` | Constante SQL existe y crea la tabla. |
| `test_estado_actual_animal_create_table_sql_existe` | Constante SQL existe y crea la tabla. |
| `test_eventos_todas_las_columnas_esperadas` | Las 13 columnas esperadas estan presentes. |
| `test_estado_actual_todas_las_columnas_esperadas` | Las 10 columnas esperadas estan presentes (sin `estado_previo_muerte`). |
| `test_eventos_fk_animal_id_a_animales` | `animal_id NOT NULL REFERENCES animales(id)`. |
| `test_eventos_fk_evento_causa_id_self_referencing` | `evento_causa_id REFERENCES eventos_ciclo_vida_animal(id)` NULLABLE. |
| `test_eventos_fk_creado_por_a_usuarios_autorizados` | `creado_por` apunta a `usuarios_autorizados(id)` (NO `usuarios`). |
| `test_estado_actual_fk_animal_id_a_animales` | `animal_id PRIMARY KEY REFERENCES animales(id)`. |
| `test_estado_actual_fk_evento_activo_id_a_eventos` | `evento_activo_id` FK a eventos, NULLABLE. |
| `test_eventos_check_tipo_evento_cubre_los_13_valores` | El CHECK enumera los 13 strings del catalogo. |
| `test_estado_actual_check_situacion_cubre_los_7_valores_mas_like_fallecido` | CHECK cubre los 7 base + LIKE 'Fallecido (%)'. |
| `test_estado_actual_check_estado_reconciliacion_cubre_los_4_valores` | CHECK cubre pending/matched/divergent/migrated. |
| `test_ensure_domain_schema_crea_las_5_tablas_en_orden` | Orden estricto de las 5 tablas (FKs respetadas). |
| `test_ensure_domain_schema_no_duplica_tablas_existentes` | Idempotencia: 2 ejecuciones = 22 calls, sin DROP/ALTER. |
| `test_NO_existe_estado_previo_muerte_en_estado_actual_animal` | Guard: no se duplica el dato de `animales.UltimoEstadoAntesDeFallecido`. |
| `test_NO_existe_creado_en_en_eventos` | Guard: la columna es `fecha_creacion` (espanol), no `creado_en` (ingles). |
| `test_eventos_tiene_columnas_soft_delete_activo` | `activo BOOLEAN NOT NULL DEFAULT true` existe en ambas tablas. |

**Test E2E (Dysflow contra prod):** se verifica via
`get-table-schema` que las 28 columnas de `animales` + las 13 de
`eventos_ciclo_vida_animal` + las 10 de `estado_actual_animal` +
los 6 indices existen en el schema real de InsForge con los nombres
correctos (lowercase por convencion de Postgres, pero el SQL los
mantiene en CamelCase/Snake segun el contrato). Verificado el
2026-06-20.

## 7. Historia de migracion

### Origen

El schema es el target de migracion del Access legacy de produccion
(`C:\00repos\codigo\APAP_ACTUAL\Registro_APAP_Alcala_datos_18.accdb`).
La tabla legacy es `TbFichaAnimal` con 26 columnas (25 de datos + el
campo `Situacion` derivado que se omite en el nuevo schema).

### Mapeo

| Legacy `TbFichaAnimal` | Nuevo `animales` | Tipo | Notas |
|---|---|---|---|
| `NCHIP` | `NCHIP` | TEXT UNIQUE NOT NULL | PK natural, identificador de display |
| `TraeNChip` | `TraeNChip` | TEXT | Flag: el animal trae chip al ingreso |
| `FIMPLANTACIONCHIP` | `FIMPLANTACIONCHIP` | DATE | Fecha de implante del chip |
| `NombreAnimal` | `NombreAnimal` | TEXT NOT NULL | |
| `Especie` | `Especie` | TEXT NOT NULL CHECK | CANINA / FELINA |
| `Sexo` | `Sexo` | TEXT NOT NULL CHECK | M / H |
| `Raza` | `Raza` | TEXT | |
| `Color` | `Color` | TEXT | |
| `Pelo` | `Pelo` | TEXT | |
| `Tamaños` (encoding legacy) | `Tamano` | TEXT | Renombrado para corregir encoding |
| `Caracter` | `Caracter` | TEXT | |
| `FNacimiento` | `FNacimiento` | DATE NOT NULL | |
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

1. `DROP TABLE IF EXISTS roles_voluntario CASCADE;`
   `DROP TABLE IF EXISTS voluntarios CASCADE;`
   `DROP TABLE IF EXISTS animales CASCADE;`
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

- `app/core/domain.py` — SQL constants (5 CREATE TABLE + 6 CREATE INDEX)
  y funcion `ensure_domain_schema` (11 calls en orden FK-dependiente).
- `app/core/insforge.py` — cliente REST de InsForge.
- `app/main.py::lifespan` — cableado del bootstrap en startup.
- `tests/test_domain.py` — 32 tests del schema (15 originales + 17 del
  slice LIFECYCLE-02).
- `C:\00repos\codigo\APAP_ACTUAL\Registro_APAP_Alcala_datos_18.accdb`
  — backend legacy de produccion (inspeccionable via Dysflow).
- `docs\discovery\feature-01-animal-lifecycle.md` — feature spec del
  legacy (referencia para el diseño del ciclo de vida).
- `docs\discovery\data-model-completeness.md` — reglas de FK,
  constraints, validaciones.
- `docs\decisiones-proyecto.md` — decisiones de producto sobre el
  dominio.
- Issue #26 — schema inicial (ingles, primera version, reemplazado).
- Issue #29 — verificacion field-by-field contra el Access legacy
  (drive de la decision del refactor).
- Issue #27 — bootstrap en startup.
- Issue #68 — schema de `eventos_ciclo_vida_animal` (LIFECYCLE-02 slice 1).
- Issue #69 — schema de `estado_actual_animal` (LIFECYCLE-02 slice 1).
- Issue #32 — epic LIFECYCLE-02 (timeline + state resolver).
