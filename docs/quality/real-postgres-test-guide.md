# Guía: cuándo un test de servicio exige Postgres real

> Issue #1205 (fricción 6 de #1146). Un fake no puede validar lo que no conoce:
> esta guía define qué comportamientos solo se demuestran contra Postgres real
> (`tests/integration/`) y cuándo basta el fake (`HandlerSqlExecutor`).

## El principio

`HandlerSqlExecutor` (`tests/sql_executor_fake.py`) valida la **forma del SQL**
(query, params, orden) contra un handler del test. No ejecuta Postgres: los
constraints, la coerción de tipos y la semántica de transacciones no existen en
el fake. Un test de servicio con fake pina **qué SQL se emite**; solo un test de
integración pina **qué hace la base de datos con ese SQL**.

## Señales de que el flujo exige Postgres real

Un flujo necesita un test en `tests/integration/` cuando cumple alguna de estas:

1. **Constraint semántica en el SQL.** La corrección depende de un constraint de
   la tabla: `UNIQUE` parcial, `CHECK`, FK. Ejemplo: la ventana TOCTOU del
   `deactivate` de voluntarios (`UPDATE ... WHERE id = $1 AND activo = true`,
   issue #282/#1099) — el fake no sabe qué es `activo = true`.

2. **`RETURNING` condicionado o CTE con efecto.** El número o contenido de las
   filas devueltas depende del estado de la base, no del handler. Ejemplo: los
   CTE de alta de terapias que desambigan FK inexistente vs inactivo (#1030).

3. **Coerción o validación de tipos por columna.** Un param serializado como
   string puede ser rechazado por una columna tipada (`uuid`, `timestamptz`).
   Vivido en PR #1138: un string no-UUID ligado a `anadido_por` pasó todos los
   tests con fake y revienta como `QueryError` contra el backend real. El fake
   no lleva esquema y no puede detectarlo (limitación declarada en su
   docstring); si el flujo liga params a columnas UUID/timestamp, necesita
   integración.

4. **Atomicidad multi-statement.** La unidad de trabajo agrupa varias escrituras
   en `transaction()` (issues #913/#914, #1066/#1067): solo Postgres demuestra
   que el fallo a mitad de flujo hace rollback de todo. Los fakes registran la
   intención (patrón `_FakeBoundExecutor`); la garantía real la da el executor.

5. **Concurrencia.** Dos sesiones compitiendo por la misma fila — el guard
   `activo = true` solo pierde una carrera contra otra sesión real.

## Qué NO exige Postgres real

- La forma del SQL emitido (los pins de wire-shape con fake son válidos y
  rápidos).
- Validación de dominio pura (Pydantic, enums, reglas de negocio sin base).
- Rutas: auth/CSRF/"no SQL en routes" (se pinean con spies, no con base).
- Datos de fila usados como fecha sin lógica de umbral (HR-10 de
  `apap-testing-strategy` rige el reloj, no esto).

## Cómo se ejercen

- Local: `APAP_TEST_PG_DSN="postgresql://...:.../..."` — sin esa variable la
  suite de integración se salta con razón (HR-15 de `apap-testing`).
- CI: job dedicado con Postgres real (ver `ci.yml`, job `integration`).

## Referencias

- Estrategia de tipos de test: `skills/apap-testing-strategy/SKILL.md` (HR-4).
- Auditoría base: [test-audit.md](test-audit.md).
- Origen de esta guía: issue #1205 (fricción 6 de #1146); caso vivido: PR
  #1138.
