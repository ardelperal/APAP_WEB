---
name: apap-testing-strategy
description: "Trigger: testing strategy, test classification, unit vs integration vs e2e, mock vs real DB, test audit, gap analysis, what type of test to write. Decides the appropriate test layer (unit/builder/service/route/integration/e2e/migration) for each piece of code in APAP_WEB, based on the 2026-08-31 test audit. Companion to apap-testing (gates and coverage); this skill is the strategy layer that says WHERE and WHAT to test."
license: MIT
metadata:
  author: ardelperal
  version: "1.0"
  last_verified: 2026-08-31
  based_on: "docs/quality/test-audit.md @ ardelperal/APAP_WEB"
---

# APAP testing strategy

## §1 Activation

Cargue esta skill cuando:

- Decida **qué tipo de test escribir** para una nueva función, ruta, flujo o flujo transaccional.
- Audite el codebase en busca de tests que mockean comportamiento que solo DB real puede verificar (FK constraints, triggers, CTE rollback, ON CONFLICT).
- Refactorice un unit test con `httpx.MockTransport` cuando el dominio tiene un comportamiento transaccional que el mock no cubre.
- Revise un PR que agrega un nuevo flujo crítico (auth, batch, soft-delete cascade) y deba exigir el test correcto.
- Responda la pregunta "¿este test debería ser unit, integration, e2e, o migration?".

No la cargue cuando:

- Solo esté ejecutando tests ya definidos sin cambiar código ni agregar nada.
- El trabajo sea exclusivamente sobre el binario Access (VBA testing tiene su propio gate — `vba-run-tests`).
- Esté escribiendo tests meta (ruff, layer-checker, coverage gate) — esos siguen el patrón existente en `tests/test_check_*.py`.

Fuentes normativas:

- `docs/quality/test-audit.md` — auditoría completa del 2026-08-31, fuente primaria de evidencia.
- `tests/integration/conftest.py` — cómo está configurada la infraestructura de DB real (`APAP_TEST_POSTGRES_DSN`).
- `tests/migration/conftest.py` — plantilla `FakeInsForge` que es el patrón a emular para nuevos módulos.
- Skill `apap-testing` — gates y cobertura (HR-1 a HR-15). Esta skill es **complementaria**, no duplicada.

## §2 Hard Rules

- **HR-1 — MUST clasificar todo nuevo test en uno de los seis tipos** del §3 antes de escribirlo. Escribir el código antes de clasificar es reject.
- **HR-2 — MUST NOT usar `httpx.MockTransport` para flujos con trigger de DB**. La auditoría de 2026-08-31 enumera `append_only_trigger_on_animal_lifecycle_events` y `chip_cascade` como casos donde el mock oculta bugs reales. Ver `docs/quality/test-audit.md` §Critical-gaps.
- **HR-3 — MUST NOT usar `httpx.MockTransport` para flujos con rollback transaccional parcial** (CTE `WITH ... AS ...`). El comportamiento de rollback contra una violación de constraint UNIQUE no se puede simular con un handler que devuelve errores. Ver `docs/quality/test-audit.md` §Critical-gaps punto 1.
- **HR-4 — MUST escribir un integration test (`tests/integration/test_<modulo>_queries_integration.py`) para todo flujo que toque FK enforcement o ON CONFLICT semantics**. La auditoría enumera `entradas`, `cesiones`, `auth_revalidation` y `chip_cascade` como P0.
- **HR-5 — MUST NOT reemplazar mocks por DB real en bloque**. El feedback loop rápido (suite default ~30 s) es una ventaja competitiva del proyecto. La migración selectiva es la regla; la sustitución masiva es reject.
- **HR-6 — MUST mantener los tests de queries (`test_*_queries.py`) byte-exactos con SQL string equality**. Son los tests más fuertes del suite según la auditoría; degradarlos a substring-match es reject.
- **HR-7 — MUST usar `FakeInsForge` para tests de migration ETL** (no Postgres real). El patrón está en `tests/migration/conftest.py`. Levantar contenedores o DB real para tests de migration es reject — el migration corre contra binario Access, no contra SQL.
- **HR-8 — MUST usar Playwright E2E (`tests/e2e/`) para validar flujos UI críticos con efectos visibles en HTML** (form post + redirect + flash). Usar curl, shell Python o inspección de DB como sustituto es reject. Ver §23 de `docs/codebase/quality-gates.md`.
- **HR-9 — MUST usar route integration in-process (`httpx.ASGITransport` + spy) para probar el contrato HTTP** sin levantar el servidor. Estos tests verifican el "no SQL en routes" gate. Ver `tests/test_acogidas_routes.py` como plantilla.
- **HR-10 — MUST NOT escribir unit tests que dependan de `datetime.now()` o `time.sleep`**. La suite default debe ser determinista. Ver `docs/quality/test-audit.md` §Flaky-tests.
- **HR-11 — MUST reportar el tipo de test elegido en el commit message o PR body** cuando el cambio toca un flujo crítico. Formato: `test(type): descripción — rationale`. Esto permite auditoría futura del balance unit/integration/e2e.
- **HR-12 — MUST consultar `docs/quality/test-audit.md` §Per-module-coverage-map antes de decidir agregar un nuevo tipo de test**. La auditoría documenta qué gaps existen; duplicar cobertura existente es reject.
- **HR-13 — MUST usar `_DefaultInsForgeSpy` o `_NoSqlRouteClient` del conftest existente** en lugar de inventar nuevos spies. El catálogo de spies es la interfaz pública entre tests y código; crear variantes es reject.
- **HR-14 — MUST preservar los ratchets existentes al refactorizar tests**. Ver skill `apap-testing` HR-14 (no relajar ratchets). Si una refactorización aumenta mutation sites o rompe un baseline, la solución es reducir el código, no relajar el gate.

## §3 Taxonomía: los seis tipos de test

| Tipo | Path | Mock | Cuándo usarlo |
|---|---|---|---|
| **Unit pure** | `tests/test_<modulo>_queries.py`, `tests/test_<modulo>_domain.py` | nada | Funciones puras: builders SQL, validadores, dataclasses. Pinnean SQL byte-por-byte. |
| **Unit service** | `tests/test_<modulo>.py` | `httpx.MockTransport` | Lógica de servicio que orquesta llamadas SQL. Verifica wire shape del SQL, no comportamiento real de DB. |
| **Route integration in-process** | `tests/test_<modulo>_routes.py` | spy + `_NoSqlRouteClient` | Contrato HTTP: status codes, redirects, CSRF, role-gated 403, fragment en HTML. Sin levantar el servidor. |
| **Application unit (hexagonal)** | `tests/test_<modulo>_application_*.py` | `_StubPort` (animals) o `FakeSqlExecutor` (lifecycle) | Slices hexagonales. Testea el dominio y la aplicación sin tocar el adaptador. |
| **Integration (real Postgres)** | `tests/integration/test_<modulo>_queries_integration.py` | nada | Flujos con FK enforcement, triggers, CTE rollback, ON CONFLICT. Requiere `APAP_TEST_POSTGRES_DSN` en CI dedicado. |
| **E2E (Playwright)** | `tests/e2e/test_<modulo>_<flujo>.py` | live server + InsForge real | Flujos UI críticos: form post + redirect, validación visual, navegación. |
| **Migration ETL** | `tests/migration/test_<flujo>.py` | `FakeInsForge` + Dysflow executor seam | ETL Access→web. Hermético; nunca toca DB real. |

## §4 Decision Gates

### Gate A — Elegir el tipo de test

| Condición | Acción |
|---|---|
| Estás testeando un builder SQL puro | Unit pure — `tests/test_<modulo>_queries.py` |
| Estás testeando lógica de servicio que emite SQL | Unit service con `httpx.MockTransport` — pero verifica §Gate-B |
| Estás testeando el contrato HTTP de una ruta | Route integration in-process — `tests/test_<modulo>_routes.py` |
| Estás testeando un slice hexagonal (animals, cesiones) | Application unit con `_StubPort` o `FakeSqlExecutor` |
| Estás testeando FK enforcement, UNIQUE constraint, trigger | **Integration con Postgres real** — `tests/integration/` |
| Estás testeando rollback parcial de CTE / batch | **Integration con Postgres real** — el mock no puede simularlo |
| Estás testeando UI con form post + redirect + flash | E2E Playwright — `tests/e2e/` |
| Estás testeando ETL contra binario Access | Migration ETL con `FakeInsForge` — `tests/migration/` |

### Gate B — Cuándo convertir un mock en integration test

Si estás manteniendo o ampliando un test con `httpx.MockTransport` y **cualquiera** de estas condiciones se cumple, debes agregar un integration test hermano en `tests/integration/`:

| Condición | Por qué el mock falla |
|---|---|
| El flujo toca un trigger (`BEFORE INSERT`, `BEFORE UPDATE`, `INSTEAD OF`) | El mock no ejecuta triggers. Ver `ANIMAL_LIFECYCLE_EVENTS_APPEND_ONLY_TRIGGER_SQL`. |
| El flujo depende de FK enforcement (insertar row con FK inválido debe fallar) | El mock no valida FK. Devuelve lo que el handler decida. |
| El flujo usa `ON CONFLICT (...) DO UPDATE` o `DO NOTHING` | El mock no resuelve conflictos; devuelve filas estáticas. |
| El flujo usa `RETURNING` con condiciones (`WHERE ... RETURNING ...`) | El mock no aplica la cláusula WHERE de la CTE. |
| El flujo es un batch con rollback parcial | El mock no simula el orden de ejecución de filas en una transacción. |
| El flujo hace soft-delete cascade (UPDATE parent + ver columnas hijo) | El mock no propaga el cambio entre tablas. |
| El flujo es auth revalidation contra DB (issue #143 path) | El mock puede fingir `auth_reval_rows` pero no verifica que el cookie + DB coincidan. |

Si **ninguna** de estas condiciones se cumple, el mock es aceptable. No convertir por convertir.

### Gate C — Cuándo NO agregar tests

| Condición | Acción |
|---|---|
| La funcionalidad ya tiene un integration test cubriendo el path crítico | No duplicar con unit service. |
| Estás escribiendo tests meta (ruff, layer-checker, coverage gate) | Seguir el patrón existente en `tests/test_check_*.py`. Esta skill no aplica. |
| El cambio es de tipo puramente cosmético (rename, format) | No agregar tests nuevos. |
| Estás probando un helper trivial sin lógica de negocio | Un unit test breve basta; no integration. |

## §5 Execution Steps

1. **Clasificar** — Determinar el tipo de test apropiado usando §3 Taxonomía y §4 Gate-A. Documentar la elección.
2. **Verificar gaps** — Leer `docs/quality/test-audit.md` §Per-module-coverage-map y §Critical-gaps. Si el módulo ya tiene un patrón canónico, seguirlo. Si no, decidir si la pieza cae en §Gate-B.
3. **Plantilla** — Usar la plantilla existente del módulo. Si el módulo no tiene tests de ese tipo, basarse en `tests/test_acogidas.py` (service), `tests/test_animals_application_*.py` (application), `tests/integration/test_acogidas_queries_integration.py` (integration), `tests/e2e/test_entradas_batch.py` (e2e).
4. **Spy/herramienta** — Usar `httpx.MockTransport` para unit service, `_NoSqlRouteClient`/`_DefaultInsForgeSpy` para route, `_StubPort`/`FakeSqlExecutor` para application, psycopg real para integration, Playwright para e2e, `FakeInsForge` para migration.
5. **Determinismo** — Verificar HR-10: nada de `datetime.now()` ni `time.sleep` ni dependencias de orden de tests.
6. **Velocidad** — El suite default debe seguir bajo 60 s. Si tu test excede 5 s, es candidato a integration o e2e, no unit.
7. **Reporte** — En el commit message, indicar el tipo elegido y la justificación: `test(integration): entradas batch rollback — Gate-B (CTE rollback unverifiable contra MockTransport)`.

## §6 Output Contract

Al usar esta skill, retornar:

| Key | Type | Description |
|---|---|---|
| `test_type` | `"unit_pure" \| "unit_service" \| "route_integration" \| "application_unit" \| "integration" \| "e2e" \| "migration"` | Tipo de test elegido según §3. |
| `module` | string | Módulo afectado (`sanidad`, `animals`, `entradas`, etc.). |
| `gate_b_triggered` | `boolean` | True si el flujo cae en §Gate-B y requiere integration. |
| `gate_b_reason` | `string \| null` | Razón específica del Gate-B (FK enforcement, CTE rollback, etc.). |
| `existing_template` | string \| null | Path al test canónico del módulo que se usó como plantilla. |
| `decision_rationale` | string | 1-2 frases explicando por qué este tipo es el correcto. |
| `companion_integration_path` | string \| null | Path propuesto si Gate-B aplicó (ej: `tests/integration/test_entradas_queries_integration.py`). |
| `commit_message_suffix` | string | Sufijo a usar en el commit: `test(<type>): <desc> — <rationale>`. |
| `audit_cross_ref` | string | Referencia al gap específico en `docs/quality/test-audit.md`. |
| `risks` | string[] | Riesgos abiertos (ej: "skill body > 700 lines, recommend split"). |
| `next_recommended` | `"write_test" \| "register_in_audit" \| "escalate_to_judgment_day"` | Próxima acción. |

## §7 Anti-patterns

| Symptom | Fix |
|---|---|
| Convertir todos los unit tests con MockTransport a integration tests en una sola PR | Migración selectiva. Priorizar P0 del audit: entradas, auth revalidation, lifecycle trigger, chip cascade. |
| Agregar un integration test para una pieza que ya tiene uno | Verificar `tests/integration/` antes de duplicar. La auditoría lista los existentes. |
| Escribir un E2E test para validar wire shape de SQL | Usar unit service con MockTransport. E2E es para UI; wire shape se valida más rápido con unit. |
| Usar `datetime.now()` o `time.sleep()` para hacer un test "realista" | Inyectar un clock o usar fechas fijas. La suite debe ser determinista. |
| Crear un spy personalizado en lugar de usar `_DefaultInsForgeSpy` | Extender el spy existente; documentar la razón. No fragmentar el catálogo de spies. |
| Inventar una nueva categoría de test (ej: "service integration") | Usar las seis categorías de §3. Si ninguna encaja, abrir un PR contra esta skill antes de escribir el test. |
| Test con assertion débil (`assert True` o `assert response is not None`) | Pinnear SQL shape, status code exacto, fragment en HTML, o behavior observable. Sin evidencia no hay test. |
| Comentar el skip en lugar de arreglarlo (`@pytest.mark.skip(reason="flaky")`) | Arreglar la flakiness. Si es estructural, abrir issue; no skip permanente sin trazabilidad. |
| Eliminar un test porque falla sin entender por qué | Investigar. Si el código cambió, actualizar el test. Si el código está mal, abrir issue `type:bug`. |
| Agregar un test que solo corre en CI pero no en local | Verificar `APAP_TEST_POSTGRES_DSN` está documentado en `CONTRIBUTING.md`. Tests huérfanos son reject. |

## §8 Self-compliance

Esta skill cumple su propio rubric:

```bash
# Body budget ≤ 700 líneas
wc -l SKILL.md

# Frontmatter con los seis campos obligatorios
head -10 SKILL.md

# Description arranca con "Trigger:"
grep -c "^description: \"Trigger:" SKILL.md

# Secciones canónicas §1 a §6 en orden
grep -E '^## §' SKILL.md

# Hard Rules numeradas HR-1 a HR-N con verbos observables
grep -E 'HR-[0-9]+ — MUST' SKILL.md

# Decision Gates y Anti-patterns son tablas
grep -E '^\| (Condition|Symptom) \|' SKILL.md

# Output Contract tiene tabla de keys
grep -E '^\| `[^`]+` \|' SKILL.md
```

Self-check pasa: frontmatter completo, ~330 líneas (target), 14 HR-N con verbos MUST/MUST NOT, 3 Decision Gates en tabla, 10 anti-patterns en tabla, Output Contract con 11 keys.

## §9 Companion skills

| Skill | Cargar junto cuando |
|---|---|
| `apap-testing` | Estés verificando gates de coverage, ratchets, o CRITICAL_HELPERS. Esta skill es la estrategia; `apap-testing` es el enforcement. |
| `code-review-expert` | Estés revisando un PR que agrega tests — verificar que la elección del tipo es la correcta según §4 Gate-A y Gate-B. |
| `judgment-day` | El cambio toca auth, secrets, CSRF, PII, o migraciones — toda decisión de testing en áreas sensibles debe pasar por dual review. |
| `apap-architecture` | Estés decidiendo entre application unit vs service unit en un slice hexagonal. |
| `apap-security` | El test cubre revalidation de auth o session lifecycle — Gate-B aplicó. |
| `documentation-alan-style` | Estés documentando la estrategia en un doc human-facing. Esta skill es runtime; el doc human-facing es castellano peninsular formal. |

## §10 References

- `docs/quality/test-audit.md` — auditoría completa del 2026-08-31 (~265 archivos clasificados).
- `docs/codebase/quality-gates.md` — §19 (coverage), §23 (E2E).
- `docs/codebase/security.md` — §11 (CRITICAL_HELPERS), §6, §29 (auth).
- `tests/integration/conftest.py` — plantilla de integration con Postgres real (`APAP_TEST_POSTGRES_DSN`).
- `tests/migration/conftest.py` — plantilla de `FakeInsForge`.
- `tests/test_animals_application_*.py` — plantilla de application unit hexagonal.
- `tests/e2e/test_entradas_batch.py` — plantilla de E2E con Playwright.
- Skill `apap-testing` en `~/.config/opencode/skills/apap-testing/SKILL.md` — gates y cobertura (complementaria).

<!-- skill-apap-testing-strategy-initial-2026-08-31 -->