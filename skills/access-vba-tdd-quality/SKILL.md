---
name: access-vba-tdd-quality
description: Trigger: cobertura, refactor-safety, cardinalidad, aserciones, deuda tecnica, harness consistency, smoke vs atómico, telemetría de performance. Contiene §4 (calidad real), §6 (telemetría). Load cuando se debate cobertura, humo vs comportamiento real, pirámide de tests, manifests, o se optimiza performance.
license: Apache-2.0
metadata:
  author: Andrés Román
  version: 2.7.0
  last_verified: 2026-08-28
  scope: ['vba', 'runtime']
  auto_invoke: ['auditing Access VBA test quality']
  tiers: ['vba', 'runtime']
---



# TDD Access VBA — Calidad y Telemetría

> Parte de la skill `access-vba-tdd-fundamentos` v2.6.1. Contiene: §4 Calidad Real (E2E, cobertura, aserciones, consistencia), §6 Telemetría de Performance. Para fundamentos/reglas de oro/contrato JSON ver `access-vba-tdd-fundamentos`. Para sandbox/aislamiento/seguridad ver `access-vba-tdd-sandbox`. Para TDD loop/checklist ver `access-vba-tdd-loop`.

> **Dysflow tool references.** This skill uses Dysflow tools (test runner `test_vba`, etc.) for telemetry capture. Tool names, flag shapes, error codes, and invocation patterns are maintained by `dysflow-usage` — that skill is the canonical source of truth. If a tool is renamed or its signature changes there, this skill's references should be re-aligned in the same change. Inline references below intentionally keep tool names visible for readability; do not duplicate flag shapes, error codes, or argument schemas here — see `dysflow-usage` for those.

---

## §4 Calidad Real — E2E, Cobertura, Aserciones, Consistencia

### 4.1 North star — refactor-safety

Un test debe sobrevivir cualquier refactor que preserve el comportamiento observable. Si reescribís la implementación interna de una función (renombrás, extraés, cambiás cómo lo hace) sin cambiar lo que garantiza, los tests **no se tocan** y la suite sigue verde. Si un refactor inocuo pone un test en rojo, el defecto es del test, no del código: **arreglálo o borralo**.

El eje real es **comportamiento vs implementación**, no unit vs E2E. Probá lo que el método **garantiza** (salida, efecto en el backend de fixture que controlás), nunca **cómo** lo hace.

### 4.2 Regla de no-humo

Los tests validan comportamiento real contra datos de fixture que el propio test controla. Un test que solo verifica que el código no explota es **humo** y no aporta nada.

```vb
' ❌ Humo — no dice nada útil
Public Function Test_NCRepository_Humo() As String
    Dim nc As NCProyecto
    Set nc = New NCProyecto
    Test_NCRepository_Humo = BuildJsonOk("ok", Nothing)
End Function

' ✅ Comportamiento real — devuelve el ID correcto y estado esperado
If nc.IDNoConformidad <> CLng(testId) Or nc.Estado <> "Abierta" Then
    Test_X = BuildJsonFail("...", logs)
End If
```

### 4.3 Cobertura — piso y diagnóstico, NUNCA un objetivo

El 80% de **métodos dignos de prueba** es un **piso de regresión y diagnóstico**, no una meta a perseguir. La cobertura te dice qué se **ejecutó**, nunca qué se **verificó**: 80% con asserts débiles no prueba nada.

**Prohibido** agregar un test acoplado a la implementación solo para llegar al número. Si una rama solo se cubre acoplándote a internals, generá deuda técnica (reporte en §4.8) y dejá la rama sin cubrir.

**Dignos de prueba**: lógica de negocio, validación, transformación, acceso DAO, orquestadores, repositorios (`Obtener*`, `Guardar*`, `Borrar*`, `Listar*`, `Existe*`), servicios de cache.
**No requieren test**: getters/setters triviales, helpers de formato sin condicionales, constantes.

### 4.4 Aserciones fuertes — reglas

- Verificar el **valor concreto**, no solo ausencia de error
- **Sad path**: establecer explícitamente el estado negativo (borrar o no insertar el dato)
- **Edge cases reales**: `Null`, ID negativo, 256 chars si el límite es 255
- **Verificar efectos secundarios**: si el método actualiza, verificar que se actualizó
- **Cardinalidad para mutaciones** (ver §4.5)

### 4.5 Cardinalidad para mutaciones — OBLIGATORIO

Cualquier test que ejecute `INSERT` / `UPDATE` / `DELETE` debe verificar **conteos antes y después**:

```vb
' ✅ Patrón obligatorio para mutaciones
countBefore = CountRows(db, "tbSolicitudes", "idSolicitud=" & idSol)
If countBefore < 1 Then
    logs(0) = "FAILED - no row to delete"
    Test_X = BuildJsonFail("no row to delete", logs)
    GoTo Teardown
End If

svc.EliminarPorIdSolicitud idSol, db

countAfter = CountRows(db, "tbSolicitudes", "idSolicitud=" & idSol)
If countAfter <> 0 Then
    Test_X = BuildJsonFail("row not deleted", logs)
    GoTo Teardown
End If

Test_X = BuildJsonOk("deleted", logs)
```

Esto convierte el test de "no explotó" a "comportamiento observable verificado". Sin cardinalidad, un test de mutación es sospecha de humo.

### 4.6 Seams e interfaces — pirámide balanceada

VBA **sí** tiene interfaces: un módulo de clase puede declarar `Implements IFoo`, y varias clases pueden implementar la misma interfaz — un seam polimórfico real, no duck typing. Esto cambia la regla anterior ("todo E2E contra el sandbox"):

- **Lógica de negocio** (validación, decisión, transformación, reglas de orquestación) → testear con un **fake en memoria** que implementa la misma interfaz. Rápido, sin sandbox, sin fixtures. El helper depende de la interfaz inyectada, no de `DAO.Database`.
- **Repositorios / capa de datos** (el borde DAO real: `Obtener*`/`Guardar*`/`Borrar*`/`Listar*`) → **E2E contra el sandbox** (la disciplina existente: `access-vba-tdd-fundamentos` §1.2, §1.3, `access-vba-tdd-quality` §4.5, `access-vba-tdd-sandbox` §5). Pocos tests, lentos, pero reales.

Meta: muchos tests rápidos de lógica + pocos lentos de datos, en vez de todo lentos (causa raíz de los timeouts de `access-vba-tdd-quality` §4.7/§6). El sandbox sigue siendo el production guard; deja de ser el default para lógica que no toca datos.

**La regla vieja sigue vigente**: **nunca mockear para evitar testear una integración real.** Los fakes aíslan *lógica* de *acceso a datos*, no sirven para saltarse el test de datos. Si un test usa un fake/stub, documentar la razón en el reporte de deuda (§4.8). Excepciones para stub: dependencias externas imposibles de sandbox-ificar (`Outlook.Application`, side effects de FS), o código que llama UI/`Screen.ActiveForm` sin poder refactorizarse en el momento.

Patrón completo, código canónico (`IRepositorio` + implementador real + fake), tabla de decisión y **spike obligatorio antes de adoptar** (verificar que Dysflow importa clases-interfaz; fallback a duck typing si no): `../access-vba-tdd-fundamentos/assets/interface-seams.md`.

### 4.7 Smoke vs atómico — separación obligatoria

| Manifest | Qué contiene | Qué NO contiene |
|---|---|---|
| `tests/tests.vba.json` | Suite atómica — un test por entrada, `expect: {ok: true}` | `*_RunAll`, agregadores |
| `tests/tests.vba.smoke.json` | Agregadores `*_RunAll` (smoke) | Tests atómicos |
| `tests/tests.vba.e2e.json` | Contrato E2E separado (si aplica) | — |
| `tests/tests.vba.slices.json` | Metadata de slices | — |
| `tests/tests.vba.strict-sequence.json` | Plan de orquestación estricta | — |
| `tests/sequences/*.json` | Secuencias pequeñas para suites que timeoutean con manifests grandes | — |

**Regla de eficiencia**: `tests/tests.vba.json` **NO debe incluir agregadores `*_RunAll`**. Si existe un `RunAll`, va en `tests/tests.vba.smoke.json` o se ejecuta directo como smoke. Mezclar tests atómicos + `*_RunAll` en la suite atómica **duplica trabajo, infla fixtures y rompe el contrato**. Es bug, no flexibilidad.

**Ubicación de los módulos `.bas`**: la carpeta `tests/` es **solo para manifests y metadata** del runner. **NO aplica a módulos fuente VBA**: los módulos importables (`Test_*.bas`, `TestHelper.bas`) viven en el árbol importable (`src/modules/`), no en `tests/`. Mover `.bas` a `tests/` por "orden" puede romper el import hacia Access.

**Slices para suites que timeoutean**: para baterías pesadas, no depender de filtros amplios del manifest si generan timeouts COM. Preferir agregadores VBA compactos por slice (`Test_<Area>_<Slice>_RunSlice`) ejecutados con una sola llamada COM, devolviendo JSON compacto (`ok`, `total`, `passed`, `failed`, `firstFailure` + logs mínimos). Ejemplo completo en `../access-vba-tdd-loop/assets/tdd-loop.md` (`Test_Cache_Riesgo_RunSlice`).

Schema completo y migración en `../access-vba-tdd-loop/assets/manifest-runner.md`.

### 4.8 Reporte de deuda técnica — template

Si una suite no puede cumplir alguna regla (cobertura < 80%, mocks necesarios, mutación de tablas de config, etc.), el reporte de deuda es **obligatorio**:

```text
## Reporte de cobertura — <NombreModulo>

### Métodos cubiertos (X/Y — Z%)
| Método | Tipo | Test |
|--------|------|------|
| ObtenerPorId | Repositorio | Test_NCRepository_ObtenerPorId_HappyPath |

### Métodos testeables pendientes (deuda de cobertura)
| Método | Motivo pendiente |
|--------|-----------------|
| ExportarPDF | No priorizado en este sprint |

### Deuda técnica — métodos no testeables por acoplamiento
| Método | Problema | Refactor sugerido |
|--------|----------|-------------------|
| GuardarNC_ConFormulario | Llama Screen.ActiveForm | Extraer lógica a método sin UI |
| EnviarCorreo | Outlook.Application interno | Recibir mailer como parámetro |

### Deuda de harness — inconsistencia entre suites
| Suite | Patrón usado | Patrón canónico | Acción |
|-------|--------------|-----------------|--------|
| Test_PCSUB | `SetTestBackend` (muta config) | `ForceLocalBackend` (lee config) | Migrar |
```

La IA **NO puede declarar una suite completa** si la cobertura está bajo el 80% sin adjuntar este reporte.

### 4.9 Consistencia del harness — inconsistencia es deuda

**Regla dura**: un proyecto debe tener **exactamente una forma** de configurar el entorno de tests. Si dos suites (`Test_PCSUB.SuiteSetup` vs `Test_CDCA.SuiteSetup`) usan métodos distintos para configurar el sandbox, el proyecto tiene **deuda de harness**, no flexibilidad.

Variaciones permitidas: ninguna. El primer test que use un patrón no canónico es un bug que se resuelve antes de merge.

### 4.10 Prohibido — mutar la tabla de configuración del backend desde tests

`SetTestBackend`-style helpers que **escriben** en la tabla de configuración productiva desde código de test están prohibidos. La tabla de configuración es estado productivo; los tests no la mutan.

Patrón correcto: `BeginTestSession` **lee** la configuración UNA vez, la cachea en `m_BackendSandboxURL` / `m_BackendSandboxPassword`, y opera contra el sandbox. Nunca escribe de vuelta.

---

## §6 Telemetría de Performance — medir antes de optimizar

Cuando una batería VBA tarda demasiado, **no optimizar por intuición**. Primero obtener telemetría.

Checklist obligatorio:

1. Revisar `durationMs` total del resultado del tool canónico de tests (current: `test_vba`, per `dysflow-usage`).
2. Revisar `summary.text`, `summary.byTag`, `summary.byPrefix`.
3. Si el runner expone `result.durationMs` por test, ordenar top 10.
4. Si no, instrumentar el runner antes de tocar código.
5. Optimizar **solo** la causa medida: fixture repetido, setup caro, DAO lento, export FS, hash, linked backend o cleanup.

Reporte mínimo:

```text
VBA main suite: tests.vba.json
Total: 42 | Passed: 18 | Failed: 24 | Duration: 235.4s

Slowest tests:
- Test_X: 42.1s
- Test_Y: 31.8s
- Test_Z: 18.2s

By tag duration:
- export: 120.0s
- hash: 80.5s
- fixtures: 20.2s

By prefix duration:
- TestHash: 85.0s
- GenerarJsonE2EPorLista: 60.0s
```

---

## Companion references

- `../access-vba-tdd-fundamentos/assets/interface-seams.md` — seams con `Implements` y límites del fake.
- `../access-vba-tdd-loop/assets/tdd-loop.md` — ejecución, timeouts y slices.
- `../access-vba-tdd-loop/assets/manifest-runner.md` — schema, separación smoke/atomic y migración.
