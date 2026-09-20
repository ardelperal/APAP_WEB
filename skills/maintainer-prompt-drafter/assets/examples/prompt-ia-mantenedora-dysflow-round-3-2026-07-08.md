# Worked example: dysflow MCP round-3 (vba_inline_execution gap)

Este es un ejemplo **completo y real** de prompt generado por esta skill. Ocurrió el 2026-07-08 en el consumer HPS, projectId `00-hps-staging`.

> **RESUELTO en dysflow v2.1.1 (PR #788) — y el diagnóstico de este prompt era INCORRECTO.**
> El bug de `vba_inline_execution` era real, pero NO por lo que este prompt supone. Verificado contra Access real: el módulo `__dysflow_inline__` **sí se inyecta** y NO hace falta compilar. La causa real es que `Application.Run` lee un prefijo con punto como calificador de **PROYECTO**, así que `__dysflow_inline__.ExecuteInline` se resolvía a un proyecto inexistente → "procedure not found". El fix corre el snippet por su **nombre pelado** y envuelve el snippet en un `Function` que retorna `result` (antes era `Sub`, que lo descartaba), habilitando introspección DAO read-only vía `returnValue`. `feat-759-no-compile` intacto; `compile_vba` sigue removido. Este ejemplo se conserva como muestra del *formato* de prompt, no como diagnóstico válido.

## Contexto del gap

El consumer HPS necesitaba saber si `TbUsuariosHistoricosLocal.ID` era Autonumérico vs Long Integer para decidir si podía incluir la columna en `INSERT INTO` con valor explícito. La regla cross-project "no hacer SQL sin conocer el ERD" (impuesta por el user el día anterior) bloqueaba el fix de producción hasta tener esa respuesta.

Flujo intentado:

1. `dysflow.get_schema` → devuelve `{name, type:4, size:4, required:true, allowZeroLength:false}` para ID. **`type:4` es Long Integer (DAO.dbLong)**, pero AutoIncrement es un ATRIBUTO de la columna, no un type code separado. Dysflow NO lo expone.
2. `dysflow.vba_inline_execution` con snippet DAO que introspecciona `Field.Attributes` → falla con `"HPS no encuentra el procedimiento '__dysflow_inline__.ExecuteInline'."` — bug del adapter 2.1.0 (el runtime no inyecta el módulo `__dysflow_inline__` antes de invocar `Application.Run`).

Esto motivó el prompt al maintainer de dysflow.

## El prompt generado

```markdown
Eres la IA mantenedora de dysflow MCP. Repo: <repo path>. Versión: 2.1.0. TDD estricto, conventional commits, no romper consumers del fleet.

## Contexto del round

Round 3 = un único gap bloqueante para introspection de DAO schema sin abrir Access manualmente.

Rounds previos:
- Round 1: capabilities block migration (CONFIG_TOP_LEVEL_FIELDS_REMOVED).
- Round 2: correcciones de seguridad + scope (mantenedor respondió a round 1).

## Lo que YA funciona (NO tocar)

Validado contra el consumer HPS (projectId `00-hps-staging`):

- `get_capabilities` — snapshot completo (`adapterVersion`, `writesProcess.enabled`, `effectiveDryRunDefault`, `humanCompilePending`).
- `get_schema` con `target: "frontend" | "backend"` y `projectId` resuelve las paths via `.dysflow/project.json` (issue #716 resuelto). Shape por columna: `{name, type, size, required, allowZeroLength}`.
- `get_schema` **NO expone** AutoIncrement, PK, UNIQUE INDEX (gap previo, NO es este round — usuarios deben seguir abriendo Access para esos).
- `link_tables`, `relink_tables`, `unlink_table`, `list_links`, `list_linked_tables`, `list_tables` operativas.
- `query_execute` (read + write), `exec_sql`, `run_script`.
- `lint_module`, `lint_form_code`, `find_references`, `get_procedure`.
- TDD gates: `validate_manifest`, `run_vba`, `test_vba` operativas. `humanCompilePending` bloquea correctamente los calls.
- **NO existe** la tool `compile_vba` ni `dysflow_compile_vba` (intencional, regla cross-project "human compiles"). NO reintroducir.
- 64 tools visibles, `writeClassToolsPermitted` correcto, `dryRunDefault:true` por default.

## Lo que falta en este round

### Bug único: `vba_inline_execution` falla con "procedure not found"

#### Síntoma verificado

Llamada de ejemplo:

\`\`\`json
{
  "tool": "dysflow.vba_inline_execution",
  "arguments": {
    "projectId": "00-hps-staging",
    "code": "Dim db As DAO.Database\\nSet db = CurrentDb()\\nDim tbl As DAO.TableDef\\nSet tbl = db.TableDefs(\"TbUsuariosHistoricosLocal\")\\nDim fld As DAO.Field\\nSet fld = tbl.Fields(\"ID\")\\nresult = \"Type=\" & fld.Type & \";Attributes=\" & fld.Attributes & \";IsAutoIncr=\" & ((fld.Attributes And 16) <> 0)\\n"
  }
}
\`\`\`

Devuelve:

\`\`\`json
{
  "ok": false,
  "procedure": "__dysflow_inline__.ExecuteInline",
  "argsCount": 0,
  "returnValue": null,
  "returnType": null,
  "byref_values": {},
  "payload": null,
  "logs": [],
  "error": "Excepción al llamar a \"Run\" con los argumentos \"1\": \"HPS no encuentra el procedimiento '__dysflow_inline__.ExecuteInline'.\""
}
\`\`\`

#### Evidencia de repro

- Reproducible en el consumer HPS con `projectId: "00-hps-staging"`. La longitud del código (< 1024 chars) no influye.
- `humanCompilePending:false`, así que NO es un gate de human-compile.
- `writesProcess.enabled:true`, `writesProject.allowWrites:true`, `effectiveDryRunDefault.vba_inline_execution:true`. El error persiste con `dryRun:true`, `dryRun:false`, o sin `dryRun`.
- El binario HPS.accdb NO contiene el módulo `__dysflow_inline__` (verificable abriendo Access: el módulo no aparece en el VBE).

#### Diagnóstico preliminar

El adapter parece llamar a `Application.Run("__dysflow_inline__.ExecuteInline", <snippet>)` pero el módulo `__dysflow_inline__` no existe en el binario. El paso "inyectar el módulo con el snippet antes del Run" no está ocurriendo, o falla silenciosamente.

Comportamiento esperado (de la descripción del tool):
> "Execute an arbitrary VBA snippet inline (no module needed) and return its result, headless."

"no module needed" sugiere inyección dinámica. La inyección no ocurre.

Posibles root causes:
1. La inyección requiere un step de escritura (`import_modules`/`export_modules`) que no se está ejecutando, o falla porque Access está abierto por otro proceso.
2. El módulo se inyecta pero no se compila antes del `Application.Run`.
3. La capitalización del procedimiento (`ExecuteInline`) es incorrecta — VBA es case-insensitive pero el runtime no.
4. Algún pre-requisito (lock file en `.dysflow/`) impide la inyección.

#### Riesgo

Consumers que necesitan leer metadata DAO en runtime (AutoIncrement, PK, UNIQUE INDEX, `.Attributes`, `.Properties`) NO pueden hacerlo con dysflow. Esto los obliga a:
- Abrir Access manualmente (rompe automation en CI / agent loops).
- O usar pruebas legacy de comportamiento (circunstancial) — HPS usó `Funciones Generales.bas:3949-3986` que hace `DELETE + AddNew + For Each` con asignación explícita a ID; Access rechazaría esa asignación si la columna fuera autonumber, así que la prueba es válida.
- O escribir un módulo helper permanente + `run_vba` (requiere human compile cada vez).

Para HPS, este gap bloqueó un fix de bug de producción.

#### Tests RED sugeridos

Test 1 (`tests/integration/mcp_inline_execution.test.ts`):

\`\`\`ts
it('runs a trivial snippet and returns the result', async () => {
  const result = await client.call('vba_inline_execution', {
    projectId: '00-hps-staging',
    code: 'result = "ok"'
  });
  expect(result.ok).toBe(true);
  expect(result.result).toBe('ok');
});
\`\`\`

Test 2:

\`\`\`ts
it('introspects DAO field Attributes via inline snippet', async () => {
  const result = await client.call('vba_inline_execution', {
    projectId: '00-hps-staging',
    code: \`Dim db As DAO.Database
Set db = CurrentDb()
Dim tbl As DAO.TableDef
Set tbl = db.TableDefs("TbUsuariosHistoricosLocal")
Dim fld As DAO.Field
Set fld = tbl.Fields("ID")
result = "Attrs=" & fld.Attributes\`
  });
  expect(result.ok).toBe(true);
  expect(result.result).toMatch(/^Attrs=\\d+$/);
});
\`\`\`

Actualmente AMBOS fallan con el error `"__dysflow_inline__.ExecuteInline no encontrado"`.

## Disciplina

- TDD estricto (RED → GREEN → REFACTOR).
- Conventional commits con scope `mcp-vba-inline-execution`.
- NO tocar las herramientas de Round 1/2 (capabilities).
- NO reintroducir `compile_vba` ni `dysflow_compile_vba`.
- Mantener `safe-by-default` y `dryRunDefault:true`.
- Mantener backwards compatibility con el consumer fleet (HPS + otros 15 worktrees).

## Acceptance output

- PR con los dos tests RED → GREEN.
- Changelog en `CHANGELOG.md`: `Fix: vba_inline_execution falla con 'procedure not found' en 2.1.0; módulo inline ahora se inyecta + compila antes del Run (#<issue>)`.
- Bump de versión a 2.1.1 (patches).
- `verify-examples-vs-runtime.ps1` agrega un test para `vba_inline_execution`.

## Quick start

\`\`\`bash
git clone <repo>
cd <repo>
git checkout -b fix/vba-inline-execution-missing-procedure
pnpm install
pnpm run dev  # arranca el MCP localmente
\`\`\`

Test repro contra el MCP local:

\`\`\`bash
curl -X POST http://localhost:<port>/mcp -d '{
  "tool": "vba_inline_execution",
  "arguments": { "projectId": "00-hps-staging", "code": "result = \"ok\"" }
}'
# Esperado: { ok: true, result: "ok" }
# Actual: { ok: false, error: "...no encuentra el procedimiento '__dysflow_inline__.ExecuteInline'..." }
\`\`\`

## Reinforcement

Mantener la regla cross-project: "los consumers que necesitan AutoIncrement / PK / UNIQUE INDEX pueden confiar en `vba_inline_execution` con la misma facilidad con la que confían en `get_schema`". Si el fix no cumple esa promesa, escalar a Round 4.
```

## Output contract cuando se entregó

```json
{
  "tool": "dysflow",
  "mode": "bug-hunt",
  "round": "round-3",
  "variant": "medium",
  "prompt_path": "docs/prompts/prompt-ia-mantenedora-dysflow-round-3-2026-07-08.md",
  "prompt_bytes": 8528,
  "verification_queries": [
    "dysflow.get_capabilities",
    "dysflow.vba_inline_execution({projectId: '00-hps-staging', code: 'result = \"ok\"'})"
  ],
  "cross_session_safe": true
}
```

## Notas pedagógicas

- **Variant=medium.** El gap es único pero requiere TDD discipline + reproducibilidad + acceptance output completo. No es short porque el síntoma necesita logs literales extensos; no es long porque es un solo gap.
- **"Lo que YA funciona" tiene ~10 bullets.** Si el tool tiene más capacidades, agrupá por familia. La función es doble: (a) que el maintainer no rompa nada, (b) que el consumidor pueda confiar en que todo lo listado sigue siendo verdad tras el fix.
- **Tests RED con código real del consumer.** No abstractos — usan `TbUsuariosHistoricosLocal` (tabla real del fleet) para que el maintainer pueda ejecutar contra el mismo setup.
- **Acceptance output incluye el test del test-runner.** El consumer usa `verify-examples-vs-runtime.ps1`; agregar un test ahí es la única forma de que el regression NO vuelva en futuros rounds.
- **"Lo que NO reintroducir"** es crítico en dysflow especificamente porque ya hubo un round (round 1) sobre capabilities — el maintainer podría "arreglar" reintroduciendo `compile_vba` pensando que ayuda. Bloquear eso aquí ahorra un round 4.
> **Historical evidence snapshot (2026-07-08), not an operational example.**
> Do not copy tool counts, flags, payloads, or defaults from this file. For current
> calls, load `dysflow-usage`, run `get_capabilities`, and inspect the target with
> `describe_tool({name:"<tool>"})`.
