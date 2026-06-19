# Registro de voluntarios

> Feature fundacional del dominio. Los voluntarios son la **entidad
> de primer nivel** que todas las features operativas referencian
> (intakes, foster stays, adopciones, terapias, salud). En el legacy
> los nombres de voluntarios viven como free-text en multiples
> tablas; en la web son una entidad propia con ID estable y FK-only
> references (BR1..BR4 del discovery, ver
> `docs/discovery/data-model-completeness.md`).

> **Slice actual:** VOL-01 (schema + service + routes + templates).
> Pendiente: VOL-03 dedup de legacy, VOL-04 FK migration, VOL-05
> validacion activa.

> **Estado de paridad con el legacy (criterio duro):** este slice NO
> ofrece aun la misma funcionalidad que el legacy. El legacy permite
> crear voluntarios auto-rellenables desde un menu de Access. Este
> slice cubre la gestion de voluntarios (crear, listar, ver, dar de
> baja). Faltan: dedup del free-text legacy (VOL-03), migracion de las
> FKs en tablas operativas (VOL-04), validacion activa en
> asignaciones (VOL-05).

## 1. Alcance

Esta feature cubre la gestion del registro de voluntarios:
alta, listado, consulta y baja (soft-delete). Es la base sobre la que
se construyen todas las features que necesitan asignar un voluntario
a una operacion (entrada, estancia, adopcion, terapia).

**Incluye:**

- Definicion SQL de la tabla ``voluntarios`` con 9 columnas (4 del
  legacy ``TbVoluntariosParaAutorrellenables`` + 5 mejoras
  justificadas: ``id`` UUID PK, ``DNI`` UNIQUE, ``fecha_alta``,
  ``updated_at``, ``activo``).
- Tabla ``roles_voluntario`` (junction) con FK a ``voluntarios`` y
  dominio CHECK en ``tipo_rol``.
- CRUD basico: crear, listar, ver detalle, desactivar (soft-delete).
- Listado de roles por voluntario.
- Templates Jinja2 + Tailwind para listar, alta y detalle.

**No incluye** (queda fuera, en otros issues):

- VOL-03: deduplicacion fuzzy del free-text legacy. Cuando aterrice,
  el script tomara los nombres repetidos en ``TbEntradas``,
  ``TbAcogidaAnimal``, ``TbAdopcion``, etc. y los consolidara en
  filas de ``voluntarios`` con su ``DNI`` como secondary key.
- VOL-04: FK migration. Reemplaza los campos free-text por FKs.
- VOL-05: validacion activa. Cualquier intento de asignar un
  voluntario inactivo a una operacion devuelve error claro (FK a
  voluntarios + check de ``activo = true`` en el momento de la
  asignacion).

## 2. Criterios de aceptacion

- [x] La tabla ``voluntarios`` existe en InsForge prod con el schema
      definido en ``app/core/domain.py`` (9 cols, 4 legacy + 5
      mejoras).
- [x] La tabla ``roles_voluntario`` existe con la FK a
      ``voluntarios`` y el CHECK en ``tipo_rol``.
- [x] ``create_voluntario`` valida ``Voluntario`` (nombre) y formato
      de ``Email`` antes de SQL; devuelve ``Voluntario``.
- [x] ``list_voluntarios`` filtra por ``activo = true`` y ordena por
      nombre alfabetico.
- [x] ``get_voluntario_by_id`` devuelve el voluntario o ``None``.
- [x] ``list_roles`` devuelve los roles del voluntario.
- [x] Email o DNI duplicado propaga el ``InsForgeError`` de InsForge
      (la ruta traduce a 409).
- [x] Las rutas HTTP ``/voluntarios`` (list, new, create, detail,
      deactivate) estan registradas y autenticadas.
- [x] Tests del service: 12 tests TDD estricto, todos en verde.
- [x] Suite completa: 111/111 tests verde.

## 3. Decisiones de arquitectura

| Decision | Eleccion | Alternativa | Por que |
|---|---|---|---|
| Entidad propia con ID | ``voluntarios`` con UUID PK | Free-text en tablas operativas | BR1 del discovery: el legacy tiene los nombres repetidos en 3+ tablas sin FK; consolidar a una entidad es el cambio minimo para evitar duplicacion. |
| Nombres en espanol | CamelCase (``Voluntario``, ``Tel1``, ``Tel2``, ``Email``, ``DNI``) | snake_case English | Mismo criterio que ``animales``: matching el legacy, cero justificacion para renombrar. |
| DNI como secondary key | Columna ``DNI TEXT UNIQUE`` agregada | Solo ``Email`` | BR3: el DNI es el identificador mas estable de una persona (no cambia), mientras que el email puede cambiar. Ademas, el legacy tiene DNI en varias tablas (TbEntradas, etc.) y se necesita para el script de dedup (VOL-03). |
| Soft-delete | ``activo BOOLEAN NOT NULL DEFAULT true`` | DELETE fisico | BR4: los voluntarios referenciados por cualquier registro de negocio NO se pueden borrar. Solo desactivar. |
| Roles como junction | Tabla ``roles_voluntario`` con UNIQUE (voluntario_id, tipo_rol) | Columna TEXT en voluntarios | BR2: los roles son atributos que pueden cambiar. Junction permite asignar/desasignar sin tocar la fila principal. |
| Dominio de roles | ``intake``, ``seguimiento``, ``acogida``, ``salud`` | Lista mas larga | Es el set que aparece en la documentacion del discovery (issue #7 del backlog). Cualquier rol nuevo se anade en una migracion. |
| Validacion de email | Regex simple ``@ in email`` | Regex RFC 5322 completo | Suficiente para el MVP. El detalle de la validacion se aborda en un ciclo futuro si hace falta. |
| Listado ordenado | Por ``Voluntario`` (alfabetico) | Por ``fecha_alta DESC`` | El usuario espera encontrar a las personas por nombre, no por orden de alta. |
| Listado filtra inactivos | ``WHERE activo = true`` | Mostrar inactivos con estilo diferente | El MVP necesita ver solo los activos; los inactivos son accesibles por id directo. |
| Auth | Cualquier usuario autorizado | Solo developer | El registro de voluntarios no es solo admin: cualquier voluntario de la protectora puede ver la lista. El admin gestiona `usuarios_autorizados`, no `voluntarios`. |

## 4. Contratos de interfaz

### 4.1 Schema SQL

```sql
CREATE TABLE IF NOT EXISTS voluntarios (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    Voluntario TEXT NOT NULL,
    Tel1 TEXT,
    Tel2 TEXT,
    Email TEXT UNIQUE,
    DNI TEXT UNIQUE,
    fecha_alta TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    activo BOOLEAN NOT NULL DEFAULT true
)

CREATE TABLE IF NOT EXISTS roles_voluntario (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    voluntario_id UUID NOT NULL REFERENCES voluntarios(id),
    tipo_rol TEXT NOT NULL CHECK (tipo_rol IN ('intake', 'seguimiento', 'acogida', 'salud')),
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE (voluntario_id, tipo_rol)
)
```

### 4.2 Funciones Python (``app/modules/voluntarios/service.py``)

| Funcion | Firma | Proposito |
|---|---|---|
| ``create_voluntario`` | ``(client, params) -> Voluntario`` | Inserta un voluntario. Valida ``Voluntario`` obligatorio y formato de ``Email``. Propaga ``InsForgeError`` en duplicados. |
| ``list_voluntarios`` | ``(client) -> list[Voluntario]`` | Devuelve todos los activos, ordenados por nombre. |
| ``get_voluntario_by_id`` | ``(client, voluntario_id) -> Voluntario \| None`` | Devuelve el voluntario (activo o inactivo) o ``None``. |
| ``list_roles`` | ``(client, voluntario_id) -> list[str]`` | Devuelve los roles asignados al voluntario. |

La constante ``VALID_ROL_TYPES = frozenset({"intake", "seguimiento",
"acogida", "salud"})`` y el enum ``RolVoluntario`` son la fuente de
verdad de los roles permitidos.

### 4.3 Rutas HTTP (``app/modules/voluntarios/routes.py``)

| Ruta | Metodo | Auth | Proposito |
|---|---|---|---|
| ``/voluntarios`` | GET | autorizado | Lista de voluntarios activos. |
| ``/voluntarios/new`` | GET | autorizado | Formulario de alta. |
| ``/voluntarios`` | POST | autorizado | Submit del formulario. |
| ``/voluntarios/{id}`` | GET | autorizado | Detalle. Muestra los roles. |
| ``/voluntarios/{id}/deactivate`` | POST | autorizado | Soft-delete. |

### 4.4 Payload del dataclass

```python
@dataclass(frozen=True, slots=True)
class Voluntario:
    id: str
    Voluntario: str
    activo: bool = True
    Tel1: str | None = None
    Tel2: str | None = None
    Email: str | None = None
    DNI: str | None = None
    fecha_alta: str | None = None
    updated_at: str | None = None
```

## 5. Modelo de datos

```
┌──────────────────────────────┐
│         voluntarios           │
├──────────────────────────────┤
│ id          UUID PK           │
│ Voluntario  TEXT NOT NULL     │
│ Tel1        TEXT              │
│ Tel2        TEXT              │
│ Email       TEXT UNIQUE       │
│ DNI         TEXT UNIQUE       │
│ fecha_alta  TIMESTAMP         │
│ updated_at  TIMESTAMP         │
│ activo      BOOLEAN            │
└──────────────────────────────┘
            ▲
            │ FK
            │
┌──────────────────────────────┐
│       roles_voluntario        │
├──────────────────────────────┤
│ id              UUID PK        │
│ voluntario_id   UUID FK        │
│ tipo_rol        TEXT CHECK     │
│   IN ('intake',               │
│    'seguimiento',             │
│    'acogida', 'salud')        │
│ created_at     TIMESTAMP       │
│ UNIQUE (voluntario_id,        │
│         tipo_rol)              │
└──────────────────────────────┘
```

### Mapeo legacy -> nuevo

| Legacy ``TbVoluntariosParaAutorrellenables`` | Nuevo ``voluntarios`` | Notas |
|---|---|---|
| ``Voluntario`` | ``Voluntario`` | NOT NULL, el nombre completo |
| ``Tel1`` | ``Tel1`` | |
| ``Tel2`` | ``Tel2`` | |
| ``Email`` | ``Email`` | UNIQUE (legacy no lo tenia) |
| -- | ``id`` UUID PK | Mejora |
| -- | ``DNI`` UNIQUE | Mejora: secondary key para dedup |
| -- | ``fecha_alta`` | Mejora: created_at |
| -- | ``updated_at`` | Mejora: tracking |
| -- | ``activo`` BOOLEAN | Mejora: soft-delete |

## 6. Plan de tests

Cubierto por ``tests/test_voluntarios.py`` (12 tests TDD estricto) y
``tests/test_domain.py`` (15 tests del schema). Total: 27 tests,
todos en verde.

| Test | Que cubre |
|---|---|
| ``test_create_voluntario_ejecuta_insert_con_parametros_esperados`` | El INSERT contiene los 5 obligatorios en el orden correcto. |
| ``test_create_voluntario_acepta_todos_los_campos_opcionales`` | El INSERT incluye los 4 opcionales. |
| ``test_create_voluntario_rechaza_nombre_vacio_antes_de_sql`` | Validacion ANTES de SQL. |
| ``test_create_voluntario_rechaza_email_sin_formato_antes_de_sql`` | Validacion de formato. |
| ``test_create_voluntario_propag_InsForgeError_en_email_duplicado`` | Duplicado propaga error. |
| ``test_create_voluntario_email_vacio_se_permite`` | Email vacio -> NULL. |
| ``test_list_voluntarios_ejecuta_select_y_devuelve_filas`` | El SELECT filtra activos y ordena. |
| ``test_list_voluntarios_devuelve_lista_vacia_sin_filas`` | Sin filas = lista vacia. |
| ``test_get_voluntario_by_id_devuelve_fila_cuando_existe`` | Get by id. |
| ``test_get_voluntario_by_id_devuelve_None_si_no_existe`` | Get by id not-found. |
| ``test_list_roles_devuelve_los_roles_del_voluntario`` | List roles. |
| ``test_list_roles_devuelve_lista_vacia_sin_roles`` | Sin roles. |

## 7. Historia de migracion

### Origen

El schema es el target de migracion del Access legacy de produccion
(``C:\00repos\codigo\APAP_ACTUAL\Registro_APAP_Alcala_datos_18.accdb``).
La tabla legacy es ``TbVoluntariosParaAutorrellenables`` con 4
columnas de datos. El resto de las tablas (TbEntradas, TbAcogidaAnimal,
TbAdopcion, TbTerapias) tienen campos free-text con el nombre del
voluntario que se deben deduplicar (VOL-03) y migrar a FK (VOL-04).

### Coexistencia con el legacy

Durante el periodo de coexistencia:
- Las altas y modificaciones en la web se replican al legacy
  mediante un script de sincronizacion (issue #26 + feature
  migracion).
- El script de sincronizacion es bidireccional: cualquier cambio en
  el legacy se refleja en la web, y viceversa.
- El script de VOL-03 dedup es responsable de consolidar los nombres
  repetidos en filas de ``voluntarios`` con ``DNI`` unico.

### DROP+CREATE en produccion

El refactor del 2026-06-19 hizo DROP de las tablas antiguas en
ingles (``volunteers``, ``volunteer_roles``) y CREATEs de las nuevas
en espanol. Las tablas estaban vacias, no hubo perdida.

## 8. Notas operacionales

### Diagnostico

Para inspeccionar la tabla desde fuera de la app:

```sql
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'voluntarios'
ORDER BY ordinal_position;
```

Para listar los voluntarios activos con sus roles:

```sql
SELECT v.Voluntario, v.Email, v.DNI,
       COALESCE(string_agg(r.tipo_rol, ', '), '(sin roles)') AS roles
FROM voluntarios v
LEFT JOIN roles_voluntario r ON r.voluntario_id = v.id
WHERE v.activo = true
GROUP BY v.id, v.Voluntario, v.Email, v.DNI
ORDER BY v.Voluntario;
```

### Mantenimiento

**Cuidado con DELETE**: la tabla tiene FKs entrantes en futuras
features (intakes, foster stays, adopciones, terapias). Si se
necesita recrear, usar ``DROP TABLE ... CASCADE``.

**Roles**: la asignacion de roles todavia no tiene UI. Se aborda
en un ciclo futuro. Por ahora, los roles se asignan directamente
por SQL:

```sql
INSERT INTO roles_voluntario (voluntario_id, tipo_rol)
VALUES ('<uuid>', 'intake')
ON CONFLICT DO NOTHING;
```

## 9. Referencias

- ``app/core/domain.py`` -- SQL constants y ``ensure_domain_schema``.
- ``app/modules/voluntarios/service.py`` -- logica de negocio.
- ``app/modules/voluntarios/routes.py`` -- rutas HTTP.
- ``app/templates/voluntarios/{list,form,detail}.html`` -- UI.
- ``app/main.py::lifespan`` -- bootstrap automatico en startup.
- ``tests/test_voluntarios.py`` -- 12 tests del service.
- ``tests/test_domain.py`` -- 15 tests del schema.
- ``C:\00repos\codigo\APAP_ACTUAL\Registro_APAP_Alcala_datos_18.accdb``
  -- backend legacy de produccion.
- ``docs/discovery/feature-02-intake-foster-adoption.md`` -- feature
  spec que documenta la necesidad de la entidad voluntario.
- ``docs/discovery/data-model-completeness.md`` -- BR1..BR4 sobre
  voluntarios (entidad propia, FK-only, no delete, dedup).
- ``docs/decisiones-proyecto.md`` -- decisiones de producto sobre
  voluntarios.
- Issues #34, #82..#86 (este slice) y pendientes #35..#38, #83
  (roles junction, dedup, FK migration, validacion activa).
