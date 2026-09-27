[← Back to Codebase Guide](../CODEBASE-GUIDE.md)

# Security

Esta página posee las reglas §6 y §29 de AGENTS verbatim, junto con resúmenes de las reglas §9 (logging), §10 (CSRF) y §11 (CRITICAL_HELPERS). Las páginas dedicadas a CSRF, logging y codegraph cubren el contrato completo.

## Regla 6 — Los defaults de seguridad deniegan, no permiten

Cuando lea un flag de sesión o payload, use como default el valor más restrictivo. Un campo ausente debe tratarse como la opción más segura.

**Incorrecto** — flag ausente concede acceso

```python
if not payload.get("is_authorized", True):
    redirect("/unauthorized")
```

**Correcto** — flag ausente deniega acceso

```python
if not payload.get("is_authorized", False):
    redirect("/unauthorized")
```

## Regla 11 — Gate de cobertura para `CRITICAL_HELPERS`

Los helpers en `app/` (funciones que matchean el regex `_row_to_*` + la lista explícita `{_redirect, _render_form, _is_duplicate_error, _validate_create_params, _build_insert_params}`) deben tener 100% de cobertura de líneas. Si añade un nuevo helper que contiene lógica de producto testeable, añádalo a `CRITICAL_HELPERS` en el mismo PR.

**Aplicación**: `scripts/pytest_plugin/coverage_gate.py` lee `coverage.json` tras pytest y falla el build si alguna entrada de `CRITICAL_HELPERS` tiene <100% de cobertura de líneas. El auto-descubrimiento de helpers vía el regex `_row_to_*` captura nuevos helpers que cumplen la convención; la lista explícita es para helpers sin regex.

## Regla 29 — Cache de auth: backend in-process único + scope por worker (issues #262, #287)

El cache de auth que respalda `require_authorized_user` (`app/core/auth_cache.py`, issue original #143) soporta solo el backend `in_process`. `APAP_AUTH_CACHE_BACKEND` queda como guard de compatibilidad: `in_process` se acepta; `redis` y todo valor desconocido fallan la validación de settings durante el arranque de la aplicación, antes de servirse cualquier request. Cada proceso worker de uvicorn posee su propio cache en memoria, así que `invalidate_auth(email)` solo alcanza al worker que la llamó y la peor ventana de staleness cross-worker es `APAP_AUTH_CACHE_TTL_SECONDS` (default 300s). El deploy actual en Coolify se confirmó el 2026-07-25 como una réplica de la aplicación usando el `CMD` del Dockerfile con Uvicorn y sin override `--workers`, así que corre un solo worker hoy. Antes de aumentar la cuenta de workers o réplicas, fije `APAP_AUTH_CACHE_TTL_SECONDS=0` para revocación inmediata al costo de un `SELECT` de autorización extra por request autenticado. Los pasos completos de deploy, verificación y rollback viven en `docs/runbooks/auth-cache-multi-worker.md`.

## Secretos históricos en `git history` — protocolo de allowlist (issue #967)

Un secreto que queda en el historial de git es **inmune al borrado del archivo** — el commit que lo introdujo permanece referenciado por SHA. Reescribir el historial (`git filter-branch`, `git filter-repo`) rompería PRs abiertos, clones y la memoria de CI, así que no es la respuesta correcta. El protocolo del repo es:

1. **Revocar o rotar la credencial** en el proveedor — esto lo hace el mantenedor, fuera del repositorio. Sin revocación, cualquier persona con acceso al historial puede usar la clave.
2. **Desactivar el camino de runtime** que la consumía (en este repo, el árbol de `app/core/adapters/insforge/` y los DI/ports asociados quedaron eliminados en `8bd9432` + este cleanup; el runtime ya no lee la clave).
3. **Allowlist por fingerprint** en `.gitleaksignore` — solo para el commit + archivo + regla + línea exactos del hallazgo histórico. Formato: `<file>:<rule>:<line>` (ver `gitleaks dir --report-format json` para los valores). Cada entry lleva un comentario con la fecha, la issue y la razón por la que no es un secreto activo. Para hallazgos del escaneo de historia (`gitleaks detect`) use siempre el fingerprint completo de modo historia `<commit>:<file>:<rule>:<line>` — incluye el SHA del commit, de modo que la entrada queda clavada al hallazgo exacto: es inmutable (el SHA nunca cambia) y específica (no cubre apariciones nuevas del mismo shape en otros commits, que sí deben fallar el gate).
4. **Verificación**: una rama de prueba con un secreto ficticio de alta entropía en el mismo shape debe seguir fallando el gate `security-deep`. Si pasa, el allowlist se volvió genérico y hay que restringirlo.

Aplicación concreta de este protocolo al `API_KEY` de InsForge que quedó en el commit inicial `7e06e58` (`opencode.json:12`, regla `generic-api-key`):

- **Issue**: #967 (cierre por chained cleanup).
- **Revocación**: confirmada por el mantenedor (InsForge está deprecado y el runtime no lo consume).
- **Allowlist**: `.gitleaksignore` línea final con comentario explicativo.
- **Verificación**: una rama de prueba con un valor `ik_*` en `opencode.json:12` falla el gate (el allowlist es por fingerprint exacto, no por regla).

Si en el futuro aparece un nuevo `API_KEY` con la misma regla `generic-api-key`, el `security-deep` job lo detectará — el allowlist no es genérico.

### Taxonomía de clasificación y triage #903

Antes de allowlistear cualquier hallazgo, clasifíquelo en una de tres clases y registre la clase en el comentario de la entrada:

| Clase | Qué significa | Acción exigida |
|---|---|---|
| Secreto real | La credencial existió y pudo ser válida | Revocar/rotar fuera del repo (paso 1 del protocolo) antes de allowlistear |
| Falso positivo | La regla dispara sobre una construcción que no es un secreto (p. ej. un kwarg cuyo valor es un nombre de archivo) | Allowlist por fingerprint completo con justificación |
| Dato de prueba | Valor ficticio de test (fixture, padding para superar la validación de settings) | Allowlist por fingerprint completo con justificación |

Triage #903 (2026-09-27): el primer escaneo de historia completa (`gitleaks detect` sobre los 1602 commits, imagen pineada por digest) reportó 11 hallazgos — 9 datos de prueba (8 filenames de storage usados como fixtures de un adaptador falso en dos commits, el padding de sesión de una suite de integración y el fixture de #381), 1 falso positivo estructural (el allowlist retirado de #381 se flaggeó a sí mismo por citar el valor entrecomillado) y **0 secretos reales**; no hubo rotaciones. Recuerde la constraint que ese falso positivo ilustra: nunca cite el valor flaggeado dentro de `.gitleaksignore`, ni siquiera en un comentario — entrecomillar el valor re-dispara la regla contra el propio allowlist.

## Imágenes base pineadas — cadencia de re-pin y política trivy (issue #1043)

El pin por digest (#338) hace la build reproducible, no segura: la capa congelada acumula CVEs mientras Debian publica arreglos que la imagen nunca absorbe. `security-deep` lee los digests del propio `Dockerfile`, así que el re-pin es el único mecanismo de remediación y este protocolo define cuándo y cómo.

### Cadencia de re-pin

- **Re-pinee cuando trivy reporta vulnerabilidades con fix disponible** (`Fixed version` no vacía) sobre los digests pineados. Ese es el disparador; no hay cadencia de calendario.
- Resuelva el digest nuevo vía la API del registry (token en `auth.docker.io`, HEAD a `registry-1.docker.io/v2/library/<img>/manifests/<tag>` con `Accept: application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json`; el `Docker-Content-Digest` de la respuesta es el pin). Nunca pinee un digest sin escanearlo antes.
- Si el tag actual de la línea en uso ya resuelve al mismo digest vulnerable y la línea está EOL (caso node 20 en #1043), suba de línea LTS completa — no hay remedio dentro de la línea congelada.
- Valide la build con las bases nuevas antes de commitear el re-pin; un bump de base puede romper la build de la wheel o de Tailwind.

### Política de `.trivyignore` para vulnerabilidades sin fix

Cuando el digest más nuevo disponible todavía arrastra vulnerabilidades sin fix publicado (trivy reporta `Fixed version` vacía), el registro `.trivyignore` es el único mecanismo de supresión sancionado:

- **Una entrada por vulnerabilidad**, con fecha de alta, expiración a 90 días y justificación inline en la misma línea del identificador. Nada global, nada sin fecha.
- **Solo vulnerabilidades sin fix disponible**. Una con fix **nunca** se ignora: el re-pin la resuelve o el gate falla — fail-closed.
- **Nunca `--ignore-unfixed`** en la línea de comandos; el registro por-identificador con justificación es el sustituto auditable.
- Cada entrada se **re-justifica al expirar**: la entrada vencida se elimina y el gate vuelve a fallar hasta que la vulnerabilidad tenga fix upstream (re-pin) o la justificación se renueve con evidencia fresca.

### Fail-closed

El gate falla ante cualquier vulnerabilidad con fix disponible no ignorada. Es deliberado: una vulnerabilidad reaparecida tras un re-pin debe detener el merge, no filtrarse en silencio. Cualquier cambio que debilite esta propiedad (flag global, expiración indefinida, ignorar una vulnerabilidad con fix) es una regresión de seguridad del repo.

## Resumen de reglas conectadas

| Regla | Página | Resumen |
|---|---|---|
| §6 | este doc | Defaults deniegan, no permiten |
| §9 | [logging-conventions.md](logging-conventions.md) | `log_safe` solo en `app/`; doce campos redactados |
| §10 | [csrf-defense.md](csrf-defense.md) | `CsrfMiddleware` + `csrf_token` en cada form post + `SameSite=Strict` |
| §11 | este doc | 100% de cobertura sobre `CRITICAL_HELPERS` |
| §29 | este doc | Cache de auth in-process; un worker = un cache |

## Core invariants

- **Default-deny en flags de seguridad**: cualquier `payload.get(key, False)` resuelve a denegado cuando la clave falta.
- **CSRF cobertura universal**: cada POST/PUT/DELETE/PATCH pasa por `CsrfMiddleware`; cada `<form method="post">` lleva `csrf_token`.
- **Log redaction automática**: doce campos PII/secret nunca aparecen en logs.
- **CRITICAL_HELPERS 100%**: la lista explícita más el regex `_row_to_*` cierra la cobertura de helpers de producto.
- **Un worker = un cache**: aumentar workers exige `APAP_AUTH_CACHE_TTL_SECONDS=0` y runbook de rollback.
- **Base images fail-closed**: los digests del `Dockerfile` se re-pinean cuando trivy reporta CVEs con fix; `.trivyignore` solo acepta CVEs sin fix, con fecha y expiración a 90 días.

## Contributor checklist

- [ ] Cada flag de auth nuevo defaultea a `False` o al valor más restrictivo.
- [ ] Ningún nuevo POST/PUT/DELETE/PATCH se sirve sin pasar por `CsrfMiddleware`.
- [ ] Cada `<form method="post">` que renderice incluye `{{ csrf_token }}`.
- [ ] Los nuevos helpers de producto se añaden a `CRITICAL_HELPERS` con su test al 100%.
- [ ] Si aumenta workers o réplicas, fija `APAP_AUTH_CACHE_TTL_SECONDS=0` y enlaza el runbook.
- [ ] Si trivy reporta CVEs con fix sobre los digests pineados, re-pinea la base (nuevo digest escaneado) en lugar de añadir entradas a `.trivyignore`.

## Navigation

Previous: [Architecture](architecture.md) | Next: [CSRF defense](csrf-defense.md)
