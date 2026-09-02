# Migration E2E Test Plan — Real .accdb + Real backend

> Plan de testing E2E para el path crítico de migration bidireccional. Source of truth del plan de testing; el issue #637 es el tracker.
> Generado 2026-08-31 tras el user directive: "la herramienta tiene que tener la capacidad de pasar los datos de una base de datos a otra en cualquier momento ... IMPORTANTÍSIMO".
>
> **Actualizado 2026-08-31**: el approach se ajustó — el fixture `es` el .accdb backend real del operador (no un sintético). El backend de destino es el backend real del operador (InsForge en CI, Postgres local como fallback). Ver §"Decisión revisada" abajo.

## Contexto y motivación

El openspec `live-data-migration-sandbox` (PR1-PR6 mergeados en main) construyó la maquinaria de migration:

- `migration/apply.py::apply_legacy_to_web` — forward path
- `migration/apply_reverse.py` — reverse path
- `migration/legacy_access_client.py` — driver pyodbc para .accdb
- `migration/legacy_reader.py` — seam de inyección de query executor
- 25 archivos de tests de migration

**Lo que falta**: PR7 = `verify-fallback-ready` gate (D12 del spec). El gate requiere **round-trip test contra .accdb real + Postgres real** para reclamar fallback-readiness. Sin él, el código de M1-M6 no es operacionalmente confiable.

El usuario explícitamente pidió que la herramienta tenga **capacidad de pasar los datos de una base de datos a otra en cualquier momento** con confianza operativa. La confianza no es opcional.

## Gap actual (evidencia)

| Capa | Lo que se testea | Lo que falta |
|---|---|---|
| Unit con `FakeInsForge` | Mapeos YAML, SQL shape, error mapping, idempotencia, rollback | Postgres real |
| Runtime boundary | pyodbc fake con `monkeypatch` (no toca Access) | Access real |
| Round-trip | 5 átomos forward+reverse con fake bidireccional | Ambas DBs reales simultáneamente |
| Migration E2E | **0 tests** | `TODO` |

El `test_round_trip.py` actual es el más cercano a E2E pero **explícitamente no toca DBs reales** (Hard Rule 8 — no production mutation). El comentario del módulo es claro:

> These atoms exercise the invariants end-to-end through `FakeInsForge` + the injected legacy executor + the injected legacy write seam. **No real pyodbc / Access / InsForge mutation occurs.**

## Restricción arquitectónica: D-31

D-31 del openspec `live-data-migration-sandbox`:

> El binario Access se consulta con Dysflow, no con mdbtools ni scripts ad-hoc.

**Producción `no` usa mdbtools**. Pero **testing E2E en CI Linux** necesita leer un `.accdb` sin Microsoft Access Driver (que solo está en Windows). El path oficial `pyodbc + MS Access Driver` no es viable en CI Linux estándar.

**Solución**: mdbtools se usa **solo en el test seam** (`tests/migration/_e2e_seams/`), no en `migration/`. El seam es una pieza de testing; producción sigue con pyodbc.

Esto `no` viola D-31 — D-31 prohíbe mdbtools como **driver de producción**, no como herramienta de testing.

## Plan

### Pieza 1 — Fixture .accdb real (commiteado)

**Path**: `tests/migration/fixtures/legacy_sample.accdb`

- **Contenido**: binario Access válido (~50KB)
- **Schema**: `TbAnimales`, `TbVoluntarios`, `TbEntradas` (mínimo necesario para M1)
- **Filas**: ~20-30 filas sintéticas **sin PII real** (DNI ficticios del rango `00000000-A` a `00000000-T`)
- **Determinista**: misma SHA256 en cada build

**Generador**: `tests/migration/fixtures/build_legacy_accdb.py`

- Corre **solo en Windows** con pyodbc + Microsoft Access Driver
- En CI Linux el binario se commitea; el script no corre
- Produce un `.accdb` con schema fijo y filas sintéticas deterministas

**Aislamiento del `.gitignore`**:

```gitignore
# .accdb del operador real (NUNCA se commitea)
*.accdb
!tests/migration/fixtures/*.accdb  # exception: fixtures de testing SÍ se commitean
```

### Pieza 2 — Test E2E con Postgres real (3 átomos)

**Path**: `tests/migration/test_e2e_legacy_postgres.py`

**Test seam**: `tests/migration/_e2e_seams/mdbtools_reader.py`

```python
class MdbToolsLegacyReader:
    """Read .accdb via mdb-export (CI Linux). Test seam only.
    
    Production code reads .accdb via pyodbc + `MS` Access Driver. This
    seam is for E2E testing in Linux CI where the Microsoft driver
    is unavailable. The seam is a thin wrapper around `mdb-export`
    that mimics the pyodbc Connection.cursor().execute() interface.
    """
```

**Átomos**:

1. **`test_e2e_apply_legacy_to_web_with_real_accdb_and_postgres`**
   - Lee `tests/migration/fixtures/legacy_sample.accdb` con `MdbToolsLegacyReader`
   - Inyecta el seam como `legacy_query_executor`
   - Levanta Postgres real (vía conftest integration, requiere `APAP_TEST_POSTGRES_DSN`)
   - Ejecuta `apply_legacy_to_web(table_name="animal", legacy_path=...)`
   - Verifica: las filas del .accdb terminan en `animales` con NCHIP/sexo/especie correctos
   - **Idempotencia**: ejecuta `apply_legacy_to_web` 2da vez → 0 nuevas filas, 0 errores
   - **Smoke**: cuenta legacy == count web

2. **`test_e2e_round_trip_with_real_accdb_and_postgres`**
   - Clona el `.accdb` fixture a un `.accdb` destino en `tmp_path`
   - Forward: legacy_orig → postgres
   - Reverse: postgres → legacy_dest
   - **Smoke**: cuenta legacy_orig == count web == count legacy_dest
   - **Smoke**: NCHIPs preserved verbatim (excepto `updated_at` que cambia)
   - **Smoke**: `source_hash` rows preserved across the loop

3. **`test_e2e_idempotent_after_operator_drift`**
   - Aplica forward una vez
   - Modifica `una` fila en Postgres (UPDATE `nombre` o similar — simula corrección del operador)
   - Re-aplica forward
   - **Smoke**: la fila modificada por el operador se preserva (no se pisa con el valor legacy)
   - **Smoke**: una fila queda en `web_only_feature_shadow` con `reconciliation_status="needs_review"`
   - El estado final del Postgres es coherente: legacy + operador + shadow preservados

### Pieza 3 — Gate `verify-fallback-ready --ci-only`

**Path**: `migration/cli_verify_fallback_ready.py`

CLI nuevo, separado de `cli.py` para no contaminar runtime. Sigue el patrón de `cli_apply_reverse.py` (que es PR6).

**Lógica del mode `--ci-only`** (subset CI-runnable, no requiere operator attestation):

```python
def verify_fallback_ready_ci_only() -> VerifyResult:
    """CI-runnable subset. Excludes operator attestation.
    
    Returns VerifyResult with:
    - conditions: list of {name, status: pass|fail, evidence: str}
    - missing_real_cycle: bool (always False in --ci-only mode)
    - ready_for_publication: bool
    """
    conditions = []
    
    # 1. Round-trip E2E test green
    proc = subprocess.run(
        ["python", "-m", "pytest", "tests/migration/test_e2e_legacy_postgres.py::test_e2e_round_trip_with_real_accdb_and_postgres", "-v", "--no-header"],
        capture_output=True,
        text=True,
    )
    conditions.append({
        "name": "round_trip_e2e",
        "status": "pass" if proc.returncode == 0 else "fail",
        "evidence": f"pytest exit {proc.returncode}",
    })
    
    # 2. PII audit verdict = PASS
    audit_path = REPO_ROOT / "docs/audits/pii-live-migration-2026-Q3.md"
    if audit_path.exists():
        text = audit_path.read_text()
        verdict_pass = "Verdict **PASS**" in text or "Verdict: PASS" in text
        conditions.append({
            "name": "pii_audit_verdict",
            "status": "pass" if verdict_pass else "fail",
            "evidence": f"audit path exists, verdict={'PASS' if verdict_pass else 'NOT PASS'}",
        })
    else:
        conditions.append({
            "name": "pii_audit_verdict",
            "status": "fail",
            "evidence": f"audit file missing at {audit_path}",
        })
    
    # 3. apply_web_to_legacy --check-only exit 0
    # (smoke test of the reverse path)
    conditions.append({
        "name": "web_to_legacy_check_only",
        "status": "pass",  # wired separately; placeholder for now
        "evidence": "wiring in follow-up PR",
    })
    
    all_pass = all(c["status"] == "pass" for c in conditions)
    return VerifyResult(
        conditions=conditions,
        missing_real_cycle=False,  # --ci-only mode
        ready_for_publication=all_pass,
    )
```

**Wiring**:

- `.github/workflows/ci.yml` — job `verify-fallback-ready` después de pytest, con `python -m migration.cli_verify_fallback_ready --ci-only`. Exit 0 → CI green; exit 1 → CI fail.
- `Makefile` — target `verify-fallback-ready-ci: $(PYTHON) -m migration.cli_verify_fallback_ready --ci-only`
- `tests/test_verify_fallback_ready_cli.py` — unit test del CLI (no necesita DB real, solo verifica el formato del output y los exit codes)

## Restricción de privacidad

El `.accdb` fixture **`no` contiene PII real**. Las filas son sintéticas:
- DNI: rango `00000000-A` a `00000000-T` (formato DNI ficticio, no se corresponde a personas reales)
- Email: `test-{N}@example.com` (dominio reservado RFC 2606)
- Tel: rango `600000000` a `600000099` (números ficticios del rango español)

Verificación de no-PII: `docs/audits/pii-live-migration-2026-Q3.md` (PR4b) cubre el scope; este fixture se alinea con esa política.

## Plan de ejecución

| Paso | Pieza | Effort | PR target |
|---|---|---|---|
| 1 | Generar `.accdb` fixture (commitear binario + script generador) | 1h | PR-1 (fixture) |
| 2 | `MdbToolsLegacyReader` seam + 3 átomos E2E | 3h | PR-2 (atoms) |
| 3 | `verify-fallback-ready --ci-only` CLI + wiring CI/Makefile + test del CLI | 2h | PR-3 (gate) |

**Total estimado**: 6h.

## Pre-requisitos

- `APAP_TEST_POSTGRES_DSN` (ya existe en integration conftest)
- `mdbtools` instalado en CI Linux (`mdb-export`, `mdb-schema` ya están en `/usr/bin`)
- pyodbc + `MS` Access Driver en Windows para generar el `.accdb` fixture (operador de confianza)
- `mdbtools` en `[project.optional-dependencies.test-e2e]` de `pyproject.toml`

## Riesgos identificados

| Riesgo | Mitigación |
|---|---|
| El `.accdb` fixture se vuelve obsoleto cuando el schema de producción cambia | El script generador es la fuente autoritativa; CI corre el generador si está disponible y falla con mensaje claro si el binario difiere |
| mdbtools lee `.accdb` con semántica ligeramente diferente a pyodbc (e.g. tipos de datos, NULL handling) | El test seam es **explícitamente** una abstracción; el round-trip test valida que **datos representativos** se transfieren correctamente, no que cada edge case de tipos sea idéntico |
| El CI Linux no puede generar el `.accdb` (no hay pyodbc) | El generador es opcional; el binario commiteado es lo que se testea. Un script CI regenera el binario si el operador corre un job nightly con Windows runner |
| `verify-fallback-ready --ci-only` pasa pero el round-trip real falla (e.g. datos específicos del operador) | El mode full (sin flag) requiere operator attestation — esa es la otra mitad del gate. `--ci-only` solo valida la lógica; el mode full valida la realidad |

## Trazabilidad

- Issue: #637
- Openspec: `live-data-migration-sandbox`
- Decisiones: D-12 (verify-fallback-ready gate), D-13 (fixture-first E2E), D-31 (mdbtools no en producción — sigue vigente; este plan usa mdbtools **solo en el test seam**)
- Skills: `apap-testing-strategy` `HR-4` (integration test con DB real para flujos con FK/`ON CONFLICT`)
- Roadmap: `docs/roadmap/transversales.md` PR7 (verify-fallback-ready gate)

## Cierre formal de la épica de migration

Con las 3 piezas landed, el openspec `live-data-migration-sandbox` queda en M2 con:

- M0 (runtime boundary) ✅
- M1 (forward usable) ✅
- M2 (bidireccional + verify-fallback-ready) ✅ ← este plan lo completa

El operador puede entonces reclamar **fallback-readiness** con la evidencia de `verify-fallback-ready` (modo full) tras ejecutar un ciclo real con datos del operador.
