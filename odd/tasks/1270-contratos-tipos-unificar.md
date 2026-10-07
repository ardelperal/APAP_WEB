# #1270 — Unify TipoContrato enum with catalogos_tipos_contrato

## Status

| Field | Value |
|---|---|
| Number | #1270 |
| Type | `type:bug` (`gap:legacy` per body) |
| Priority | (no priority label) |
| Status | `status:approved` |
| Branch | `bug/1270-contratos-tipos-unificar` |
| Worktree | `apap-app-worktrees/1270-contratos-tipos-unificar/` |
| Sub-issue of | #1109 (DOC-01 contratos) — blocking acceptance criteria for adopciones / cesiones / preadopciones / acogidas judiciales |

## Objective

Eliminate the silent drift between `app.modules.contratos.domain.tipos_contrato.TipoContrato` (StrEnum, 8 valores sin tilde, citado como espejo de `TbContratosAnexos`) and the `catalogos_tipos_contrato` catalog (sembrado desde `TbPlantillas`, 8 valores CON tilde y nombres distintos). Hoy solo 2 de los 11 valores que aparecen en el código coinciden; el resto bloquea la generación de contratos para adopciones, cesiones, preadopciones y acogidas judiciales.

## Problem and why

Diagnóstico tras inspección del código y de la doc:

- **El enum `TipoContrato` no se usa en código de producción** (grep en `app/` sin matches). Solo aparece en tests.
- **El servicio `app/modules/cesiones/service.py` ya consulta el catálogo** con `codigo='Cesión'` (con tilde) y lo documenta como la fuente para resolver el FK del tipo (`CONTRATO_TIPO_CESION`).
- **El test que pinea los 8 valores** (`tests/test_contratos_template_engine.py::test_tipo_contrato_enum_covers_eight_legacy_types`) cita `docs/legacy-signed-contract-flow.md` §4 como fuente. Esa §4 del doc es **"Pregunta Clave: ¿Se conserva el documento de ParaFirma?"** — **no contiene tal enum de 8 valores**. El pin del test no tiene respaldo.
- **El catálogo `catalogos_tipos_contrato.codigo` es la única fuente con evidencia P1 real**: sembrado desde `TbPlantillas` con comentario P1 en `app/core/catalogs.py` y mapping documentado en `app/core/catalogos/tipo_contrato.py` (Spanish spelling canónico, con tildes).

Comparativa de las dos listas (extracto del body de la issue):

| Enum `TipoContrato` (sin tilde) | Catálogo `codigo` (con tilde) | Coinciden? |
|---|---|---|
| `Entrada` | `Entrada` | sí |
| `Acogida` | `Acogida` | sí |
| `Acogida Judicial` | — | no |
| `Adopcion` | `Adopción` | no (tildes) |
| `PreAdopcion` | — | no |
| `Cesion` | `Cesión` | no (tildes) |
| `Reserva` | — | no |
| `Entrega` | `Entregado a Propietario` | no |
| — | `Ficha de Seguimiento` | no |
| — | `Ficha Sanitaria Gatos` | no |
| — | `Ficha Sanitaria Perros` | no |

**Conclusión**: el enum es una invención del modelo web sin respaldo legacy. El catálogo es la fuente operativa real. La raíz del bug **no es un typo** — es un modelo que duplica sin evidencia el dominio del legacy.

## Evidencia verificable

- `app/modules/contratos/domain/tipos_contrato.py` — StrEnum `TipoContrato` con 8 valores.
- `app/core/catalogs.py:282-308` — `CATALOGOS_TIPOS_CONTRATO_SEED_SQL` con 8 valores sembrados desde `TbPlantillas`.
- `app/modules/cesiones/service.py:132` — `"SELECT id FROM catalogos_tipos_contrato WHERE codigo = $1"` (consulta real en producción).
- `app/modules/cesiones/service.py:368-372` — mensaje de error explícito que dice `"catalogos_tipos_contrato is missing the 'Cesión' row"`.
- `docs/legacy-signed-contract-flow.md` §4 — el test que pinea los 8 valores cita este doc, pero su §4 no contiene ningún enum de tipos de contrato.
- `tests/test_contratos_template_engine.py:39-58` — pin de los 8 valores.
- `tests/test_contratos_template_engine.py:71-72` — pin de equality `TipoContrato.ADOPCION == "Adopcion"`.
- Reproducción documentada: `POST /contratos` con `tipo=Adopcion` falla al resolver contra el catálogo; `tipo=Entrada` y `tipo=Acogida` resuelven limpio.
- El mock `_ContratosSqlSpy` oculta el drift en los tests de ruta del slice.

## Alcance y no objetivos

### Incluido

- **Eliminar el StrEnum `TipoContrato` de `app/modules/contratos/domain/tipos_contrato.py`** y reemplazarlo por un único punto de verdad: el catálogo `catalogos_tipos_contrato.codigo`.
- Proveer un **type alias** `TipoContrato = str` (o un `NewType`) que refleje el `codigo` del catálogo, sin volver a inventar valores estáticos.
- Cambiar los consumidores del enum (todos en tests) para que lean el catálogo directamente o usen el type alias.
- Eliminar el test pineado `test_tipo_contrato_enum_covers_eight_legacy_types` y reemplazarlo por uno que afirme que **los tipos de contrato del catálogo son los únicos que el slice conoce**, leídos desde la fuente.
- Eliminar el test pineado `test_tipo_contrato_str_mixin_supports_legacy_string_equality` (asumía StrEnum; ya no aplica).
- Quitar el mock `_ContratosSqlSpy` que oculta el drift en los tests de ruta (reemplazarlo por un test que use el catálogo real o un fake que lo refleje).
- Re-validar los criterios de aceptación de #1109 (DOC-01) que ahora pasan: `tipo=Adopcion` resuelve a la fila `codigo='Adopción'` del catálogo; idem para `Cesion`, `PreAdopcion` (que requiere seed nuevo), `Acogida Judicial` (idem).

### Fuera de alcance

- Modificar la seed del catálogo (no agrego ni quito filas en esta issue).
- Cambiar el nombre de la columna `catalogos_tipos_contrato.codigo` ni el dataclass `app/core/catalogos/tipo_contrato.py::TipoContrato`.
- Cambiar `app/modules/cesiones/service.py` (ya usa el catálogo correctamente).
- Refactor de tests que no dependen del enum drift.
- Tocar la presentación UI del selector de tipo (futura issue).

## Criterios de aceptación

- [ ] El módulo `app/modules/contratos/domain/tipos_contrato.py` ya no exporta un `StrEnum`.
- [ ] Cualquier consumidor del antiguo enum se compila y pasa sus tests con la nueva representación.
- [ ] Existe un test que enumera los `codigo` del catálogo `catalogos_tipos_contrato` y los expone como los **únicos** tipos de contrato que el slice conoce.
- [ ] El test pineado de los 8 valores del enum ficticio ya no existe (o se reemplaza por uno que afirme el catálogo como fuente).
- [ ] `pytest tests/test_contratos_template_engine.py -v` verde.
- [ ] `pytest tests/test_contratos_full_flow.py -v` verde.
- [ ] `pytest tests/test_contratos_local_backend_pdf.py -v` verde.
- [ ] `make verify` verde (suite completa, 85%+ coverage, `check_crap` ok, mypy ok, ruff ok).
- [ ] El cuerpo de la issue #1270 cierra con `Closes #1270` en el PR.

## Plan de validación

1. **RED**: agregar un test que afirme `TipoContrato` ya no es un `StrEnum` y que el catálogo es la fuente. Correr — falla.
2. **GREEN**: convertir el `StrEnum` en un type alias / dataclass proxy; actualizar todos los call sites; correr tests — verde.
3. **REFACTOR**: quitar el mock `_ContratosSqlSpy`; re-correr — verde.
4. **Verificación final**:
   - `make verify` (gate pre-MVP §15.1).
   - `python -m pytest tests/ -v --no-header` (suite completa).
   - `mypy app/` y `ruff check app/ tests/`.
   - `make check-issue-specs` (que sigue verde para issues nuevas).
5. **CI gate**: `ci / required` en el PR — debe pasar antes de merge.

## Dependencias y riesgos

- **Riesgo (decisión de producto)**: eliminar el enum es un cambio mayor. La doc actual del módulo afirma que "el listado exhaustivo abajo es la single source of truth"; el cuerpo de la issue la contradice. La decisión final corresponde al mantenedor (ver §3 abajo).
- **Riesgo técnico**: 30+ referencias al enum en tests (varios archivos). Hay que tocarlas todas; TDD cubre el riesgo.
- **Riesgo de regresión en #1109**: el slice de DOC-01 tiene 7 PRs encadenados abiertos. Si esta rama entra antes que ellos, podría reventar su batería. Plan: mergear **antes** de los PRs de #1109 para que la batería e2e cierre limpia; avisar al reviewer de #1109.
- **Compatibilidad legacy P1**: la doc del enum actual cita un doc (`legacy-signed-contract-flow.md` §4) que **no respalda los 8 valores**. Eliminar el enum no rompe fidelidad legacy — al contrario, **corrige** una invención del modelo web que nunca tuvo evidencia.
- **Bloqueos**: ninguno. No depende de otras issues abiertas no-CI.
- **Rollback**: revert del merge; el enum ficticio vuelve a estar, sin valor pero sin daño.

## Decisión de producto pendiente (§3 ODD)

**Pregunta al mantenedor** (bloqueante para empezar TDD):

1. ¿Confirmás que el catálogo `catalogos_tipos_contrato.codigo` (sembrado desde `TbPlantillas` con P1) es la fuente de verdad única para los tipos de contrato?
2. Si sí, ¿el `TipoContrato` del slice pasa a ser un type alias del catálogo (recomendado) o se mantiene como un `StrEnum` derivado dinámicamente del catálogo en cada arranque?
3. Si la respuesta a 1 es no (la fuente son los 8 valores inventados), ¿de dónde sale la evidencia legacy que falta en `legacy-signed-contract-flow.md`?

Sin respuesta, la issue queda en estado "spec completa, approach en disputa con el módulo actual, requiere decisión de producto".
