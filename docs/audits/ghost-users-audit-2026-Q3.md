# Auditoría: usuarios fantasma y 500 al añadir duplicado — 2026 Q3

**Scope**: cierre de los defects #277 (admin_add_user con `InsForgeError` sin manejar) y #278 (emails case-sensitive que crean "ghost users" en `usuarios_autorizados`). Cambios en `app/core/auth_helpers.py`, `app/core/auth.py`, `app/core/auth_cache.py`, `app/core/admin_helpers.py`, `app/main.py`, `app/templates/admin.html` y sus tests asociados.

**Methodology**: TDD estricto (RED → GREEN → REFACTOR) sobre los cuatro contratos (normalización, validación, duplicado, invalidación de caché por variantes de case); verificación manual del flujo admin y de la deduplicación de caché; procedimiento operator documentado en `docs/runbooks/auth-email-normalization.md`.

**Date**: 2026-07-26.

**Verdict**: **PASS**. Ambos defects quedan cerrados por este PR; el anti-patrón §32.P4 (manejo parcial de excepciones) y el caso de perímetro §32.P1 (email no normalizado en el borde, instancia #278) dejan de reproducirse en código de producto. Riesgo residual: filas heredadas con casing mixto requieren un pase manual de deduplicación (ver runbook).

---

## Scope

| Área | Evidencia |
|---|---|
| Helper canónico (single source of truth) | `app/core/auth_helpers.py` (nuevo) — `normalize_email` + `validate_email_format` |
| Capa de servicio | `app/core/auth.py` — `add_authorized_user` con pre-check + mapeo defensivo de `InsForgeError`; `get_user_by_email` con `normalize_email` |
| Capa de caché | `app/core/auth_cache.py` — clave case-folded, `_case_variants` y `invalidate_auth` que barre todas las variantes |
| Helpers de admin | `app/core/admin_helpers.py` (nuevo) — `_pop_flash` y `_redirect_with_flash` |
| Rutas HTTP | `app/main.py` — `GET /admin` con flash contextual y `POST /admin/users` con `_add_user_or_error` |
| Plantilla | `app/templates/admin.html` — bloque de error con `error_message` / `error_type` |
| Tests nuevos | `tests/test_auth_helpers.py` (10 átomos), `tests/test_auth.py` (+5 átomos para #277/#278), `tests/test_auth_cache.py` (+3 átomos para invalidación por variantes), `tests/test_admin.py` (+1 átomo para error rendering) |
| Contrato de repo | AGENTS.md §4 (single source of truth), §25 (sin helpers duplicados), §32.P1 (perimeter blindness), §32.P4 (partial exception handling) |
| Operación | `docs/runbooks/auth-email-normalization.md` (procedimiento operator para filas heredadas con casing mixto) |
| Audit histórico | n/a (PR nuevo, sin superseded) |
| Dependencias | Ninguna añadida; `pyproject.toml` no cambia |

Fuera de alcance: OAuth, cookies, roles, autenticación, esquema de base de datos
(la columna `email` sigue siendo `TEXT UNIQUE NOT NULL` y la constraint se
mantiene — la normalización se aplica en el borde, no en el motor).

## Methodology

1. **Fuente de verdad del problema**:
   - **#277** (AGENTS.md §32.P4): `admin_add_user` capturaba `ValueError` pero
     dejaba escapar `InsForgeError` (p.ej. una violación de UNIQUE residual
     entre el pre-check y el INSERT) hacia un 500 no manejado. No existía
     handler global de excepciones en `app/` que la recogiera.
   - **#278** (AGENTS.md §32.P1, instancia nombrada): el email nunca se
     normalizaba en el borde. `usuarios_autorizados.email` es `TEXT UNIQUE` con
     collation sensible a mayúsculas, así que `Maria.Lopez@Example.COM` y
     `maria.lopez@example.com` eran dos usuarios distintos. La capa de caché
     heredaba el problema porque la clave era el string exacto pasado.

2. **TDD estricto**:
   - Safety net inicial: 2546 passed antes del primer commit.
   - **RED** (commit `5de64b7`): 5 failed, 2541 passed. Cubría los cinco
     átomos: normalización, validación de formato, duplicado vía pre-check,
     duplicado vía `InsForgeError`, e invalidación de caché por variante de
     case.
   - **GREEN** (commit `f41e717`): todos los átomos en verde; 2568 passed
     netos. Refactor mínimo para mantener tamaño de `app/main.py` por debajo
     del presupuesto (AGENTS.md §21): los helpers de flash se extrajeron a
     `app/core/admin_helpers.py`.

3. **Verificación de la caché por variantes de case**: se añadieron átomos
   explícitos en `tests/test_auth_cache.py` que simulan una entrada cacheada
   bajo `Maria@Example.COM` y demuestran que `invalidate_auth("maria@example.com")`
   la invalida sin acceso a la fila canonical. Esto cierra el vector residual
   "el código escribe en canonical pero el lector usa el string original".

4. **Verificación de no duplicación de helper** (AGENTS.md §25):
   `scripts/check_rules.py` Detector 10 no marca ningún `_opt` /
   `_required_text` / `_optional_text` adicional. `normalize_email` vive solo
   en `app/core/auth_helpers.py` y se importa desde `auth.py` y
   `auth_cache.py`. El grep `grep -rn 'normalize_email\|validate_email_format'
   app/` confirma un único definidor y dos importers.

5. **Verificación completa del gate local**:
   - Lint: `ruff check .` y `python scripts/check_rules.py .` sin errores.
   - Typecheck: `python -m mypy` sin errores sobre `app/` y `migration/`.
   - Tests: 2568 passed, 2 skipped, 1 deselected (PostgreSQL real).
   - Cobertura global: 89.42% (por encima del suelo 80% de AGENTS.md §19).
   - `CRITICAL_HELPERS`: 21/21 al 100% (AGENTS.md §11).
   - Module size y route size: sin violaciones (AGENTS.md §21, §28).

6. **Procedimiento operator** (filas heredadas con casing mixto): el cambio
   de aplicación es no destructivo — no muta filas existentes por sí solo. Se
   documenta en `docs/runbooks/auth-email-normalization.md` el SQL de
   detección de duplicados y el procedimiento de renombrado perdedor
   (`disabled + <timestamp>@archive.local`) para que el operador pueda
   limpiar la tabla antes del siguiente backup restore.

7. **Limitaciones conocidas**:
   - La deduplicación de filas heredadas requiere una migración manual one-shot
     por entorno (no incluida en este PR). El runbook fija el procedimiento.
   - El helper `_case_variants` genera todas las variantes con un solo swap
     por carácter más el swapcase completo (2^N para N caracteres alfabéticos,
     capped aquí a N+2 por construcción). Esto cierra el vector realista
     (legado humano, normalmente una o dos mayúsculas). Si en el futuro se
     detecta un patrón de casing más agresivo, se sustituye `_case_variants`
     por una invalidación completa (`invalidate_all`) sin tocar la API.

## Findings

| ID | Severidad | Hallazgo | Mitigación | Status |
|---|---|---|---|---|
| GH-277-1 | CRITICAL | `admin_add_user` no manejaba `InsForgeError` cuando el INSERT caía con violación de UNIQUE residual entre el pre-check y la escritura; el 500 escapaba sin contexto (§32.P4 — partial exception handling). | Pre-check explícito (`_CHECK_DUPLICATE_EMAIL_SQL`) + `except InsForgeError` defensivo que re-mapea a `ValueError("email already authorized: <canonical>")`; helper `_add_user_or_error` que captura `ValueError` y lo renderiza como flash. Átomos: `test_add_authorized_user_rejects_duplicate_via_insforge_error`, `test_admin_add_user_with_duplicate_email_shows_error`. | Cerrado |
| GH-278-1 | WARNING | El email nunca se normalizaba en el borde de auth, así que mixed-case de la misma dirección creaba dos filas en `usuarios_autorizados` (§32.P1 — perimeter blindness, instancia nombrada). | `normalize_email` (strip + lowercase) como single source of truth en `app/core/auth_helpers.py`; aplicado en `add_authorized_user`, `get_user_by_email`, y como case-fold en la clave de caché. Átomos: `test_add_authorized_user_normalizes_email_before_insert`, `test_get_user_by_email_lowercases_input`, `test_add_authorized_user_invalidates_cache_for_normalized_email`. | Cerrado |
| GH-278-2 | WARNING | Una entrada cacheada bajo un casing no normalizado (legacy) sobrevivía a `invalidate_auth(<canonical>)` porque la clave del dict era el string exacto. | `_case_variants(email)` que barre todas las variantes con un swap por carácter más swapcase completo; `invalidate_auth` invalida cada variante. Átomos: `test_invalidate_auth_drops_case_variant_entries`, `test_invalidate_auth_sweeps_swapcase_variants`. | Cerrado |
| GH-278-3 | SUGGESTION | Filas heredadas con casing mixto en `usuarios_autorizados` siguen presentes hasta que el operador ejecute el runbook de deduplicación. | Runbook `docs/runbooks/auth-email-normalization.md` con SQL de detección, procedimiento de renombrado del perdedor a `disabled + <timestamp>@archive.local`, snapshot pre-migración y rollback. Sin acción de código en este PR — la app sigue funcionando correctamente con filas mixtas (las trata como la misma identidad canónica). | Cerrado por docs; ejecución manual one-shot por entorno |
| GH-278-4 | SUGGESTION | El admin template solo mostraba mensajes de error cuando la ruta redirigía; el flash sobrevivía en la cookie de sesión y no se renderizaba hasta el siguiente GET. | `_pop_flash` extrae el flash del payload firmado, lo limpia (re-firma sin `_flash`) y `_redirect_with_flash` lo inyecta con `SameSite=Strict` y `secure=True`. Bloque `error_message` / `error_type` en `admin.html`. Átomos: `test_admin_add_user_with_duplicate_email_shows_error`, `test_admin_renders_user_table_for_developer` (no error message en éxito). | Cerrado |
| GH-277-2 | SUGGESTION | `app/main.py` crecía hacia el presupuesto de 700 líneas (AGENTS.md §21) por los helpers de flash. | Extracción a `app/core/admin_helpers.py` (70 líneas, bien por debajo del presupuesto). | Cerrado |

## Security decisions

- **Single source of truth**: `normalize_email` y `validate_email_format`
  viven solo en `app/core/auth_helpers.py` (AGENTS.md §4 + §25). Ningún otro
  módulo redefine estos helpers; el Detector 10 de `scripts/check_rules.py`
  lo pinaría si se reprodujera el patrón histórico de `_opt` /
  `_required_text` / `_optional_text`.
- **Defense in depth**: el pre-check `_CHECK_DUPLICATE_EMAIL_SQL` es la vía
  rápida y testeable; el `except InsForgeError` defensivo cubre el residuo
  entre el SELECT y el INSERT (carrera TOCTOU imposible por la UNIQUE
  constraint). Ambas vías terminan en el mismo `ValueError` que el route
  renderiza.
- **No regresión de caché**: el case-fold en clave + `_case_variants` en
  invalidación cierran los dos vectores (escritura canónica vs. lectura
  legacy con casing original). El contrato de worker-local de
  `APAP_AUTH_CACHE_BACKEND=in_process` no cambia; ver
  `docs/runbooks/auth-cache-multi-worker.md` para el comportamiento multi-worker.
- **No PII nueva en logs**: la normalización ocurre antes de la serialización
  del payload de log (`log_safe` con la lista cerrada de 15 campos). El helper
  no añade campos nuevos a la lista de redacción; el email sigue siendo
  redactado por nombre de campo.
- **Sin secretos nuevos**: ninguna credencial, URL ni token se añade.
  `pyproject.toml` no cambia.

## Verdict

**PASS**. Los defects #277 y #278 quedan cerrados en código de producto con
cobertura TDD explícita y un runbook operator para la limpieza one-shot de
filas heredadas. Los anti-patrones §32.P4 (partial exception handling) y §32.P1
(perimeter blindness, instancia email normalization) dejan de reproducirse en
este PR — la capa de auth ahora normaliza en el borde y maneja tanto errores
de dominio como errores de transporte de forma diferenciada.

Riesgo residual: las filas heredadas con casing mixto permanecen en la tabla
hasta que el operador ejecute el procedimiento documentado en
`docs/runbooks/auth-email-normalization.md`. La aplicación las trata
correctamente (las ve como una sola identidad canónica), pero aparecen dos
veces en la lista del panel admin hasta la deduplicación manual.

Aceptación: el operador debe confirmar el verdict y ejecutar el runbook antes
de la próxima ventana de backup restore, idealmente antes del primer deploy
con un nuevo `initial_admin_email` para evitar que el seed choque contra una
fila heredada.