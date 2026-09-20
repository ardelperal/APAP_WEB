Eres la IA mantenedora de dysflow MCP. Repo: <repo path>. Branch: <branch>. Versión: 2.1.0+. TDD estricto, conventional commits, no romper consumers en fleet.

## Contexto del round

Round 4 = un único bug en el linter `lint_module`. La regla `identifier-safety` está reportando como `error` cualquier identificador VBA que contenga caracteres no-ASCII (tildes, eñes, cedillas, etc.), con el mensaje:

> "Identifier 'Sí' contains non-ASCII characters; use ASCII-safe VBA identifiers for reliable import/compile round-trips."

Rounds previos:
- Round 1: capabilities block migration (CONFIG_TOP_LEVEL_FIELDS_REMOVED).
- Round 2: correcciones de seguridad + scope (post-respuesta del mantenedor al round 1).
- Round 3: gap en `vba_inline_execution` (procedimiento `__dysflow_inline__.ExecuteInline` no se inyecta antes del Run). Pendiente en el repo del consumer.

## Lo que YA funciona (NO tocar)

- `import_modules` con sha256 match (round-3 verificó en vivo).
- `compile_vba` removido estructuralmente (decisión cross-project "human compiles" — política, no feature).
- `lint_module` ejecuta las 5 reglas correctas: `option-declaration`, `identifier-safety`, `declaration-order`, `arg-type-match`, `forbidden-name`.
- `apply:true` / `dryRun:false` consistente en toda la API de writes.
- `effectiveDryRunDefault` policy `safe-by-default`.
- `verify-examples-vs-runtime.ps1` corre contra runtime real.

## Lo que falta en este round

### Bug único: la regla `identifier-safety` rechaza identificadores VBA con tildes (false positive)

#### Síntoma verificado

Source `HPS.accdb`, módulo `src/classes/UsuarioHPS.cls:404`:
```vb
If m_EnOficina = EnumSiNo.Sí Then
```

Linter emite:
```
rule: identifier-safety
line: 404
severity: error
message: Identifier 'Sí' contains non-ASCII characters; use ASCII-safe VBA identifiers for reliable import/compile round-trips.
```

Conteo en el codebase consumer `HPS` (verificado 2026-07-08):
- `UsuarioHPS.cls`: 10 errores (`Sí` repetido en varias líneas, `Error` shadowing).
- `UsuarioServicio.cls`: 2 errores.
- Estimado cross-fleet: ~50+ errores en 11+ proyectos consumer (HPS, gestion_riesgos, no_conformidades, condor, cadete, etc.).
- **Cero errores de compile reales** — el human-compile del user en Access (Debug → Compile) completa sin errores. El código corre en producción desde hace años con estos identificadores.

#### Evidencia de repro

Caso 1 — el código es válido y compila:
```vb
' Módulo: TestFixtureUnicode.bas
Attribute VB_Name = "TestFixtureUnicode"
Option Compare Database
Option Explicit
Public Const ConstanteConTilde As String = "Sí"
Public Function AñoActual() As Integer
    AñoActual = 2026
End Function
```

Resultado esperado: el módulo se lintea como `isClean: true` (todos los identificadores con tildes son VBA legal).
Resultado actual: el módulo se lintea como `isClean: false` con N errores de `identifier-safety`.

Caso 2 — import + compile manual sin issues:
- `dysflow.import_modules({moduleNames: ["UsuarioHPS"], dryRun: false})` → `status: "ok"`, sha256 match source/destination, no truncation.
- User abre `HPS.accdb` en Access → Debug → Compile → completa sin errores.
- El módulo corre en producción con `EnumSiNo.Sí`, `AñoActual()`, etc.

#### Diagnóstico preliminar

VBA acepta identificadores Unicode nativamente en cualquier locale que los soporte (Spanish, Portuguese, French, German, Italian, etc.). El módulo `access-vba-tdd-fundamentos` §1.9 (skill consumer-side) documenta explícitamente:

> "Caracteres acentuados corruptos (`EnumSiNo.S?` en lugar de `EnumSiNo.Sí`) — generalmente artefacto de display de PowerShell, NO corrupción real. Verificar los bytes del archivo antes de 'arreglar': los bytes UTF-8 de `ó` son `0xC3 0xB3`, no `0x3F`."

La regla `identifier-safety` contradice directamente la documentación de la skill consumer. El mensaje "for reliable import/compile round-trips" es un non-sequitur: el import sí funciona (sha256 match verificado repetidamente), el compile sí funciona (verificado por user en 2026-07-08).

Causa raíz probable: la regla se programó pensando en exports de código a sistemas externos (JSON Schema validators, ASCII-only DBs, etc.) que pueden tener problemas con non-ASCII. Pero eso es problema del export-target, no del identificador VBA. El linter aplica una restricción innecesaria al código que **permanece en VBA**.

#### Riesgo

1. **Alert fatigue en developers**: falsos positivos constantes erosionan la confianza en el linter. Problemas reales se ignoran.
2. **Agentes IA corrompen código**: el skill `access-vba-tdd-fundamentos` §1.9 trata los errores de lint como bloqueantes. Agentes que sigan esa directriz pueden intentar "ASCII-izar" identificadores, rompiendo la lógica. Ejemplo concreto: cambiar `EnumSiNo.Sí` por `EnumSiNo.Si` elimina la tilde, pero el `Enum` queda con un valor `Si` (sin tilde) que no es lo que el código VBA original distingue. **Corrupción silenciosa de la lógica de negocio.**
3. **Cross-fleet**: 11+ proyectos consumer con VBA en español/portugués. Todos afectados.
4. **Contradice el skill documentado**: agents que siguen `access-vba-tdd-fundamentos` §1.9 y ven `isClean: false` actúan por la doc del skill, contradiciendo la regla del linter. Conflicto fuente-de-verdad.

#### Test RED sugerido

Test 1 — fixture con Unicode válido:
```ts
it('accepts VBA identifiers with non-ASCII characters (Spanish/Portuguese/French/etc.)', async () => {
  const fixtureModule = 'TestFixtureUnicode';
  // fixture.bas: ConstanteConTilde As String = "Sí", Function AñoActual() As Integer ...
  const result = await client.call('lint_module', { module: fixtureModule });
  // Esperado: isClean: true (todos los identificadores con tildes pasan)
  // Actual: isClean: false, identifier-safety violations
  expect(result.isClean).toBe(true);
  const idSafetyDiags = result.diagnostics['identifier-safety'] || [];
  expect(idSafetyDiags.length).toBe(0);
});
```

Test 2 — regression de carga real:
```ts
it('imports and human-compiles a Unicode-identifier module without truncation', async () => {
  const fixtureModule = 'TestFixtureUnicode';
  // After lint test above passes
  const impResult = await client.call('import_modules', { moduleNames: [fixtureModule], dryRun: false, verbose: true });
  expect(impResult.result[0].status).toBe('ok');
  expect(impResult.result[0].verbose.truncated).toBe(false);
  expect(impResult.result[0].verbose.source.sha256)
    .toBe(impResult.result[0].verbose.destination.sha256);
});
```

Test 3 — opcional: `verify-examples-vs-runtime.ps1` agrega el fixture Unicode al corpus.

#### Acceptance output

- PR con tests RED → GREEN.
- Changelog en `CHANGELOG.md`: `Fix: identifier-safety lint rule no longer rejects valid VBA identifiers with non-ASCII characters (Spanish/Portuguese/French/etc. are first-class VBA citizens). (#<issue>)`.
- Bump de versión a 2.1.2 (patch).
- `verify-examples-vs-runtime.ps1` agrega fixture Unicode al corpus.

## Disciplina

- TDD estricto (RED → GREEN → REFACTOR).
- Conventional commits con scope `lint-identifier-safety` o similar.
- NO tocar las otras 4 reglas del linter (`option-declaration`, `declaration-order`, `arg-type-match`, `forbidden-name`) — todas funcionales.
- NO cambiar el comportamiento del linter en otros aspectos (severity, formato de output, posición de reporte).
- Mantener `safe-by-default` y `dryRunDefault:true`.
- Si el fix requiere un flag opt-in (e.g., `allow_unicode_identifiers: false` en `.dysflow/project.json` para proyectos que exportan código a sistemas ASCII-only), ofrecerlo como opt-in, NO como default. Default = aceptar Unicode.

## Quick start

```bash
git clone <repo>
cd <repo>
git checkout -b fix/lint-identifier-safety-allow-unicode
pnpm install
pnpm run dev  # arranca el MCP localmente
```

Test repro contra el MCP local:

```bash
# 1. Crear fixture Unicode
cat > /tmp/lint-unicode-fixture.bas <<'EOF'
Attribute VB_Name = "TestFixtureUnicode"
Option Compare Database
Option Explicit
Public Const ConstanteConTilde As String = "Sí"
Public Function AñoActual() As Integer
    AñoActual = 2026
End Function
Public Sub CódigoPostal()
    MsgBox "Código"
End Sub
EOF

# 2. Importar el fixture a un .accdb de prueba
dysflow.import_modules({ moduleNames: ["TestFixtureUnicode"], dryRun: false })

# 3. Lint — debe ser isClean: true
dysflow.lint_module({ module: "TestFixtureUnicode" })
# Esperado: isClean: true (todos los identificadores con tildes son válidos en VBA)
# Actual: isClean: false, N identifier-safety violations
```

## Reinforcement

Mantener la regla cross-project: **"VBA source code puede y debe usar identificadores en el idioma natural del equipo (español, portugués, francés, alemán, etc.). El linter debe detectar problemas REALES del código (sintaxis, shadowing de globales, landmines de line-continuation, orden de declaraciones, argumentos mal tipados), NO imponer restricciones culturales sobre el idioma del código."**

Si el fix necesita scope-reduction (no detectar non-ASCII para evitar problemas de export-target), documentar el rationale y ofrecerlo como opt-in por proyecto. NO como default.

Si el fix requiere una nueva regla separada (`lint-export-target-unicode`, `lint-external-system-safe-encoding`, etc.) que sea explícitamente opt-in, ofrecerla en el mismo PR. Pero la regla `identifier-safety` por default debe aceptar Unicode en VBA.

## Referencias cruzadas

- Round-3 prompt (`vba_inline_execution` gap): este PR es independiente, no relacionado. Pero si el maintainer quiere consolidar fixes en una sola release, son ambos Non-Breaking.
- Skill `access-vba-tdd-fundamentos` §1.9: la skill consumer documenta que los bytes UTF-8 son válidos. La regla del linter debe alinearse con esa documentación.
- Cross-fleet impact: 11+ proyectos consumer con VBA en español/portugués. La regresión cruza proyectos.
> **Historical evidence snapshot (2026-07-08), not an operational example.**
> Do not copy tool counts, flags, payloads, or defaults from this file. For current
> calls, load `dysflow-usage`, run `get_capabilities`, and inspect the target with
> `describe_tool({name:"<tool>"})`.
