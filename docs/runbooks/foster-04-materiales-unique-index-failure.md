[← Back to README](../../README.md)

# foster-04-materiales-unique-index-failure.md

Este runbook es el procedimiento del operador para recuperar un fallo de creación del índice único parcial en `estancia_materiales` durante el despliegue de FOSTER-04 (#46).

## Quick Navigation

| Sección | Propósito |
|---|---|
| Cuándo abrir este runbook | Disparadores que justifican la apertura del runbook |
| Lista de comprobación previa | Auditoría previa y captura de instantáneas |
| Pasos de despliegue | Procedimiento de despliegue y de deduplicación |
| Verificación | Señales de éxito tras la deduplicación y el reinicio |
| Reversión | Camino no destructivo cuando la deduplicación no es viable |

## Cuándo abrir este runbook

Abra este runbook cuando `ensure_domain_schema` falle durante el arranque de la aplicación con cualquiera de los dos errores siguientes:

```
relation "estancia_materiales" already exists
DETAIL: Key (estancia_id, material_id)=(...) is duplicated.
```

```
ERROR: could not create unique index "estancia_materiales_active_unique"
DETAIL: Key (estancia_id, material_id)=(...) is duplicated.
```

Ambos errores significan que la aplicación no puede arrancar porque la aplicación no puede crear el índice único parcial debido a filas activas duplicadas preexistentes en `estancia_materiales`.

## Lista de comprobación previa

Antes de desplegar el esquema de FOSTER-04 (#46) PR A a cualquier entorno que ya contenga datos en `estancia_materiales`:

- [ ] Confirme que `estancia_materiales` se ha auditado en busca de pares activos duplicados `(estancia_id, material_id)`.
- [ ] Si existen duplicados, ejecute el procedimiento de deduplicación de la sección siguiente **antes** del despliegue.
- [ ] Ejecute `python -m migration status --table estancia_materiales` (cuando se fusione el issue #168; mientras tanto, consulte InsForge directamente con `psql` o el panel de InsForge).
- [ ] Verifique que la tabla `web_only_feature_shadow` no contiene conciliaciones pendientes (la limpieza es una preocupación aparte).

## Pasos de despliegue

La migración del esquema se aplica de forma automática mediante `ensure_domain_schema(client)` en el primer arranque de la aplicación (la función se invoca desde el `lifespan` de FastAPI en `app/main.py`). No se requiere ejecución manual de SQL.

```bash
# Despliegue: fusionar PR B + PR C primero, luego esta rama.
# En el arranque, ensure_domain_schema ejecuta las tres sentencias de FOSTER-04:
#   1. CREATE TABLE IF NOT EXISTS materiales
#   2. CREATE TABLE IF NOT EXISTS estancia_materiales
#   3. CREATE UNIQUE INDEX IF NOT EXISTS estancia_materiales_active_unique
```

Si el arranque falla con el error de índice, la aplicación **no** arranca. Revierta el PR de FOSTER-04 (o el conjunto completo A + B + C) al commit anterior en `main`.

### Procedimiento de deduplicación (cuando falla la creación del índice)

Paso 1: liste los duplicados en `estancia_materiales` (sólo filas activas):

```sql
SELECT estancia_id, material_id, COUNT(*)
FROM public.estancia_materiales
WHERE activo = true
GROUP BY estancia_id, material_id
HAVING COUNT(*) > 1;
```

Paso 2: para cada par duplicado, decida qué fila conservar:

- **Conservar**: la fila con `fecha_alta` más reciente.
- **Soft-delete** (`activo = false`): las restantes.

Paso 3: aplique el soft-delete:

```sql
UPDATE public.estancia_materiales
SET activo = false, updated_at = now()
WHERE id IN (
  SELECT id FROM (
    SELECT id, ROW_NUMBER() OVER (
      PARTITION BY estancia_id, material_id
      ORDER BY fecha_alta DESC
    ) AS rn
    FROM public.estancia_materiales
    WHERE activo = true
  ) t
  WHERE rn > 1
);
```

Paso 4: verifique que no quedan duplicados:

```sql
SELECT COUNT(*) FROM (
  SELECT estancia_id, material_id
  FROM public.estancia_materiales
  WHERE activo = true
  GROUP BY estancia_id, material_id
  HAVING COUNT(*) > 1
) t;
```

Resultado esperado: 0.

Paso 5: reinicie la aplicación. `ensure_domain_schema` completará la creación del índice único parcial.

## Verificación

Tras la deduplicación y el reinicio, valide:

- [ ] La aplicación arranca limpiamente.
- [ ] `python -m migration status --table estancia_materiales` (cuando se fusione #168) muestra 0 conciliaciones pendientes.
- [ ] Smoke: `GET /materiales` devuelve 200 con la lista de materiales.
- [ ] Smoke: `GET /acogidas/{id}/materiales` (cuando se fusione PR C) devuelve 200 con la lista de materiales por estancia.

## Reversión

Si la deduplicación no puede completarse (por ejemplo, los duplicados son datos de negocio legítimos que el usuario desea preservar):

1. **No** elimine manualmente el índice único parcial (se recreará en el siguiente arranque).
2. **No** elimine las tablas `materiales` o `estancia_materiales` (la aplicación depende de ellas).
3. **Revierta los PR A + B + C de FOSTER-04** (la DDL del índice único parcial se añade en PR A; revierta los commits de fusión sobre `main`).
4. Abra un issue de seguimiento que documente el conflicto de datos que bloqueó el despliegue.
5. El usuario (operador) decide entre las siguientes opciones:
    - (a) Añadir una migración de datos única que fusione los duplicados manualmente.
    - (b) Cambiar el índice único parcial por un índice no único (pierde la guarda contra condiciones de carrera).
    - (c) Añadir un nuevo concepto de dominio (por ejemplo, "lote de material") que desambigüe el mismo par `(estancia, material)`.

## Documentos relacionados

- PR #166 (FOSTER-04 PR A): PR que introdujo el índice único parcial.
- Comentario de revisión `jd-judge-b BLOCKER-2` sobre PR #166.
- `AGENTS.md` §13 — obligación de runbook para acciones del operador.
- `AGENTS.md` §18 — exclusión mutua web ↔ legacy y sincronización obligatoria.
- Issue #168 — `migration/apply.py` + bootstrap (pendiente de seguimiento que añade el comando `migration status`).