---
name: vba-query-decoupler
description: Trigger: sql inline, sql en vba, desacopla consulta, query en código, querydef. Desacopla sentencias SQL inline o hardcodeadas de los módulos de código VBA, transformándolas en QueryDefs o consultas SQL parametrizadas externas.
license: Apache-2.0
status: active
requires: codegraph-vba, dysflow MCP; for current tool names and flags → see `dysflow-usage` skill.
metadata:
  author: Andrés Román
  version: 1.0.0
  last_verified: 2026-08-22
  scope: ['vba', 'runtime']
  auto_invoke: ['decoupling inline SQL in VBA modules']
  tiers: ['vba', 'runtime']
---



# vba-query-decoupler

Workflow para identificar, extraer y desacoplar código SQL incrustado en código VBA, garantizando seguridad, mantenibilidad y previniendo errores específicos del motor de base de datos Access.

## Activation

Load when:

- Hay SQL inline (o hardcodeado) dentro de un módulo VBA (`.cls`/`.bas`) que se quiera desacoplar como `QueryDef` o constante centralizada.
- Se necesite parametrizar SQL para evitar concatenación insegura (`"WHERE ID = " & id`).
- Se esté migrando SQL embebido a una forma segura frente al gotcha del campo Memo en `QueryDef`.

Do NOT load when:

- El código no es VBA (web, .NET, Python) — esta skill gobierna exclusivamente `DAO.QueryDef` en Access.
- No hay SQL embebido que desacoplar — el código ya usa `QueryDef`/consulta externa.
- Se quiere modificar la definición de tablas en lugar del SQL que las consulta — esa tarea es de `dysflow` `create_table` / `drop_table`, no de este workflow.

## Hard Rules

- **HR-1. MUST externalizar todo string SQL complejo** (de más de una línea o con joins/condiciones dinámicas) como una consulta guardada (QueryDef) o constante centralizada. Prohibido dejar SQL inline en módulos VBA.
- **HR-2. MUST parametrizar SQL** mediante QueryDefs. Prohibido concatenar variables en strings SQL (`"WHERE ID = " & id`). Usar `qdf.Parameters("p_X") = valor` antes de `qdf.Execute dbFailOnError`.
- **HR-3. MUST evitar QueryDef con parámetros sobre campos Memo** (Long Text): DAO trunca el parámetro a 255 caracteres o falla con error. Para INSERT/UPDATE sobre Memo, usar Recordset (`Edit`/`Update`, `rs!CampoMemo = sTextoLargo`) o declarar el parámetro como `MEMO` en la cabecera SQL.

## Decision Gates

| Situation | Action |
|---|---|
| Paso 1 — buscar SQL embebido en `.cls`/`.bas` | Use `codegraph_explore` filtrando por palabras clave SQL (`SELECT`, `INSERT`, `UPDATE`, `DELETE`, `INNER JOIN`) en archivos de código; no en strings literales dentro de tablas/constantes externas. |
| Paso 1 — encontrar SQL inline pero el archivo no es VBA | STOP, esta skill no aplica; redirigir a la skill del stack correspondiente. |
| INSERT / UPDATE con datos largos sobre campo Memo | Vía Recordset (`Edit`/`Update`, `rs!CampoMemo = sTextoLargo`) — soporta tamaño ilimitado, evita el truncado a 255 chars. |
| Lectura o SELECT sobre campo Memo vía `QueryDef` | Declarar el parámetro como `MEMO` en la cabecera SQL para forzar la coerción; preferir Recordset para escritura. |
| QueryDef simple (no Memo, sin joins complejos) | Aplica HR-1/HR-2 estándar; basta extracción a `QueryDef` con `[p_Parametro]`. |
| Ya existe un `QueryDef` equivalente | Reusar el existente en lugar de crear uno nuevo; consolidar primero vía `codegraph_explore` para mapear consumidores. |

## Execution Steps

### Paso 1: Identificación
Usa `codegraph_explore` para buscar patrones de asignación de strings que contengan palabras clave SQL (`SELECT`, `INSERT`, `UPDATE`, `DELETE`, `INNER JOIN`) dentro de los archivos de código (`.cls`, `.bas`).

### Paso 2: Extracción y Parametrización
1. Extrae el SQL inline y reemplaza las variables concatenadas por marcadores de parámetros (`[p_Parametro]`).
2. Crea la consulta guardada (QueryDef) correspondiente en Access o regístrala como una consulta de catálogo en el repositorio.

### Paso 3: Refactorización del Código VBA
Reemplaza la llamada original por la ejecución del QueryDef paramétrico:
```vba
' Antes
db.Execute "UPDATE MiTabla SET Campo = '" & valor & "' WHERE ID = " & id

' Después (Vía QueryDef seguro)
Dim qdf As DAO.QueryDef
Set qdf = db.QueryDefs("qryUpdateCampo")
qdf.Parameters("p_Valor") = valor
qdf.Parameters("p_ID") = id
qdf.Execute dbFailOnError
qdf.Close
```

### Paso 4: Verificación
1. Tras el `import_modules`, el **humano compila** en Access (Debug ▸ Compile). → See `dysflow-usage` skill for current compile contract.
2. Corre la suite de tests unitarios/integración (`access-vba-tdd-fundamentos`) para asegurar que la query procesa correctamente los datos y respeta el límite del tipo de campo Memo.

## Output Contract

| Key | Type | Description |
|---|---|---|
| `extracted_queries` | array<string> | QueryDef names created or updated (one per extracted inline SQL) |
| `refactor_summary` | object | Per-file counts of inline SQL statements replaced, grouped by `.cls`/`.bas` module |
| `warnings` | array<string> | Memo-field risks, manual compile reminders, and ambiguous call sites skipped |

## Anti-patterns

| Symptom | Fix |
|---|---|
| Leaving inline SQL untouched in VBA modules | Extract to a saved QueryDef with `[p_Parametro]` placeholders per Paso 2 |
| Renaming a QueryDef without previewing consumers | Run `codegraph_explore` first to map the call sites that reference it |
| Writing a Memo-bound parameter through `QueryDef.Execute` | Use the Recordset path (Edit/Update) or declare the parameter as `MEMO` in the SQL header |
| Skipping the post-import compile gate | Ask the human to run Debug ▸ Compile in Access before declaring the refactor done |
