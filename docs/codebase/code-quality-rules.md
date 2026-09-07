[← Back to Codebase Guide](../CODEBASE-GUIDE.md)

# Code quality rules

Esta página posee las reglas restantes de AGENTS que no tienen su propia página dedicada por longitud o temática. Las reglas §1-§7 viven en [layer-boundaries.md](layer-boundaries.md); §9 en [logging-conventions.md](logging-conventions.md); §10 en [csrf-defense.md](csrf-defense.md); §11, §6 y §29 en [security.md](security.md); §14 en [codegraph-conventions.md](codegraph-conventions.md); §15 en [merge-workflow.md](merge-workflow.md); §16 en [process.md](process.md); §17 en [orchestrator-discipline.md](orchestrator-discipline.md); §18, §31 y §33 en [architecture.md](architecture.md); §19, §20, §23 y §24 en [quality-gates.md](quality-gates.md); §21 y §28 en [module-size-budgets.md](module-size-budgets.md); §25, §26 y §27 en [import-hygiene.md](import-hygiene.md); §32 en [anti-patterns.md](anti-patterns.md).

## Regla 8 — Sin librerías deprecadas, sin DeprecationWarnings

Cuando añada o actualice una dependencia Python en `pyproject.toml`, **el mínimo pineado debe ser un release no deprecado**. "Deprecado" aquí significa:

- El proyecto upstream ha EOL formalmente la major version (por ejemplo, psutil 6.1.x fue la última con soporte Python 2.7; 7.x es la línea actual).
- La librería emite `DeprecationWarning` al importar o al uso básico en el rango Python objetivo (aquí `>=3.11`).
- La librería tiene un sucesor publicado y recomienda migración.

### Cómo verificar antes de pinear

Use el **MCP context7** para consultar el estado actual de cualquier dependencia antes de añadirla a `pyproject.toml`:

1. `mcp__context7__resolve-library-id` con el nombre de la librería (por ejemplo, "psutil", "fastapi", "pydantic") — elija el resultado más reputado.
2. `mcp__context7__query-docs` con la consulta "latest version current release stable Python 3.11 3.12 recommended install pip" o similar.
3. Lea la línea "Latest version" / "Current stable" y confirme que la versión que va a pinear es la que upstream considera soportada, no una línea legada.

Pinee al **suelo current major.minor**, no a una línea legada. Ejemplo: cuando se añadió psutil para `app/core/migration/lock.py`, context7 confirmó que 7.2.x es la estable actual; pineamos `psutil>=7.0` (el suelo del major actual) en lugar de `>=5.9` (una línea legada).

### Cómo verificar localmente tras pinear

`pip install -e ".[dev]"` en un venv fresco debe tener éxito **y** `python -c "import thelib"` no debe emitir ningún `DeprecationWarning`. La suite pytest del proyecto tiene `-W error::DeprecationWarning`, así que cualquier warning de librería se vuelve un fallo de CI — esa es la red de seguridad, no un sustituto de verificar upstream.

## Regla 12 — Doc de auditoría para features sensibles

Si su PR toca auth, secrets, cookies, CSRF, XSS, idempotencia o PII, debe crear o actualizar un doc en `docs/audits/<feature>-audit-YYYY-Qn.md` con: Scope, Methodology, Findings (tabla de severidad), Verdict. Plantilla: `docs/audits/xss-audit-2026-Q2.md`.

**Aplicación**: revisión de PR (el doc de auditoría es un ítem del checklist). `scripts/check_audit_and_runbook.py` es una ayuda de desarrollador que marca cambios a paths sensibles (`app/core/auth*`, `app/core/csrf*`, `app/core/session*`, `app/core/logging*`, `app/core/migration/`) y sugiere crear o actualizar un doc de auditoría.

## Regla 13 — Runbook para código que requiere acción del operador

Si su PR introduce o cambia una rotación de secretos, paso manual de deploy, invalidación de cache, trigger de cron, cambio de env-var, o cualquier operación que el usuario deba ejecutar manualmente, debe crear un runbook en `docs/runbooks/<thing>.md` con secciones: When to trigger, Pre-deploy checklist, Deploy steps, Verification, Rollback. Referencie el runbook desde la descripción del PR.

**Aplicación**: revisión de PR. `scripts/check_audit_and_runbook.py` marca cambios a `app/core/config.py` (env-var settings) y sugiere creación de runbook. El chequeo es una ayuda de desarrollador, no un gate de CI — la responsabilidad del operador se documenta en el PR.

## Regla 22 — Separación SQL/service: construcción de query como seam propio

Los services nuevos o refactorizados separan **construcción de query** de **validación/orquestación**. Los strings SQL y su shaping de parámetros viven en un `queries.py` dedicado (o módulo builder) por módulo de feature; el service importa esos builders, aplica validación de dominio y habla con el cliente. El punto es testeabilidad: la forma del SQL debe ser asertable en un test unitario plano sin levantar transporte, LocalBackend o HTTP.

En un slice convertido este seam es `adapters/local_backend/<slice>_local_backend_queries.py`, junto al adapter que lo usa ([architecture.md](architecture.md) §33.3). SQL nunca aparece en `application/`.

**Incorrecto** — SQL interpolado inline entre validación y mapeo (untesteable sin transporte)

```python
def update_material(client, material_id, form):
    if not form.get("nombre"):
        raise ValueError("nombre required")
    client.execute_sql(
        f"UPDATE materiales SET nombre = $1 WHERE id = $2", [form["nombre"], material_id]
    )
```

**Correcto** — el builder de query es una función pura, el service orquesta

```python
# app/modules/materiales/queries.py
def build_update_material(material_id: str, nombre: str) -> tuple[str, list]:
    return "UPDATE materiales SET nombre = $1 WHERE id = $2", [nombre, material_id]

# app/modules/materiales/service.py
def update_material(client, material_id, form):
    if not form.get("nombre"):
        raise ValueError("nombre required")
    sql, params = queries.build_update_material(material_id, form["nombre"])
    client.execute_sql(sql, params)
```

Esto aplica a **services nuevos y a cualquier service existente siendo refactorizado** (por ejemplo, cuando se divide un módulo baselinado por §21, el seam extraído es exactamente este). No manda un rewrite big-bang de services existentes.

**Aplicación**: revisión de PR. Un PR que añade un service con SQL inline mezclado con validación/orquestación, o refactoriza uno sin introducir el seam de query, debe bloquearse con un puntero a esta regla.

## Regla 30 — Los docstrings son contratos sincronizados

Los docstrings son parte del contrato de código: las afirmaciones sobre comportamiento actual, inputs, outputs, errores o efectos colaterales deben estar cubiertas por un test. Las referencias a issues/PRs y cicatrices de producción que son útiles para onboarding deben etiquetarse como contexto histórico (no contrato) y preferiblemente moverse a `docs/` con un enlace; esta política complementa la regla §31 de Protocol.

**Chequeo de drift barato (requerido en review)**: por cada afirmación de comportamiento, identifique el test que la prueba; verifique que cada símbolo referenciado aún existe; y verifique que cada referencia a issue/PR aún describa el código actual. Si una afirmación no tiene test, añada uno o reescríbala como contexto histórico explícitamente no-contractual.

```python
# Historical context — non-contract: see docs/audits/<feature>-audit-YYYY-Qn.md.
# Current contract: invalid tokens return 401 and never reach the service.
```

**Aplicación**: revisión de PR usando el checklist de arriba. No añada un nuevo detector AST para matching de prosa; la heurística es intencionalmente barata y outcome-focused, mientras el límite del Protocol de §31 se enforza independientemente.

## Core invariants

- **Dependencias no deprecadas**: pinea al suelo current major.minor, valida con context7 antes.
- **Audit doc por feature sensible**: auth, secrets, CSRF, PII, XSS, idempotencia → `docs/audits/<feature>-audit-YYYY-Qn.md`.
- **Runbook por acción del operador**: rotación, deploy manual, cache invalidation, cron, env-var → `docs/runbooks/<thing>.md`.
- **Query builder como seam**: SQL solo en `queries.py` (legacy) o `adapters/local_backend/<slice>_local_backend_queries.py` (hexagonal).
- **Docstrings sincronizados con tests**: cada afirmación conductual tiene un test que la prueba.

## Contributor checklist

- [ ] Cada dependencia nueva se pinea al suelo current major.minor y se verifica con context7.
- [ ] Cualquier PR sobre auth, secrets, cookies, CSRF, XSS, idempotencia o PII carga un doc de auditoría.
- [ ] Cualquier PR que cambie una operación de operador carga un runbook enlazado desde la descripción.
- [ ] Cada service nuevo o refactorizado tiene SQL en un `queries.py` separado, no inline.
- [ ] Cada docstring con afirmación de comportamiento tiene un test que lo pruebe.

## Navigation

Previous: [Anti-patterns](anti-patterns.md) | Next: [CSRF defense](csrf-defense.md)
