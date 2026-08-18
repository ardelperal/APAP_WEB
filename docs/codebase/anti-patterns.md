[← Back to Codebase Guide](../CODEBASE-GUIDE.md)

# Anti-patterns

Esta página posee la regla §32 de AGENTS verbatim: ocho formas recurrentes detectadas por la auditoría completa del codebase del 2026-07-25 (issue #294). Cada patrón nombra su instancia del 2026-07-25 para que la regla se mantenga concreta. Cite por número en review: "esto es §32.P4".

## §32 — Anti-patrones: rechace estos por nombre

La auditoría completa del codebase del 2026-07-25 (issue #294) encontró que la mayoría de los defectos no eran equivocaciones independientes sino **ocho formas recurrentes**. Las instancias individuales se rastrean como issues propios; esta regla existe para que las *formas* se rechacen en review antes de producir nuevas instancias. El proyecto está pre-MVP — esta es la ventana donde las convenciones endurecen, y un anti-patrón que sobrevive a MVP sobrevive para siempre.

### §32.P1 — Ceguera de perímetro

El hardening se concentra donde el trabajo es interesante (generaciones de cache de auth, comparación de tokens CSRF, listas de redacción de PII) mientras el borde HTTP no recibe nada.

*Instancia*: cero security headers en `app/` (#276), sin rate limiting (#286), email nunca normalizado en el borde (#278) — todo mientras el modelo de auth de núcleo se revisó cuatro veces (#143, #145, #146, #262).

**Criterio**: un PR que endurece un mecanismo interno debe enunciar, en una línea, cuál es la exposición de borde correspondiente y si ya está cubierta. "No aplicable" es respuesta válida; el silencio no.

### §32.P2 — Defaults inseguros que aún arrancan

Un secret faltante degrada a una app insegura-pero-corriendo en lugar de un deploy fallido.

*Instancia*: `session_secret` envía un placeholder de desarrollo funcional y `insforge_service_key` defaultea a `""` (#275). Un env var faltante significaba que cada cookie de sesión se firmaba con un secret publicado en este repositorio.

**Criterio**: ningún campo de `Settings` que porte un secret puede tener un default que funcione en producción. O no tiene default y pydantic falla, o el arranque lo valida y rehúsa servir. Un default que es *conveniente en dev* debe gated con un flag de desarrollo explícito.

**Incorrecto** — la app arranca y queda silenciosamente insegura

```python
session_secret: str = "dev-only-change-me-in-production"
```

**Correcto** — conveniencia dev, rechazo producción

```python
session_secret: str = "dev-only-change-me-in-production"

# …y en el lifespan, antes de servir:
if not settings.debug and settings.session_secret == _DEV_PLACEHOLDER:
    log_safe("startup.config_invalid", reason="session_secret_placeholder")
    raise RuntimeError("APAP_SESSION_SECRET must be set in production")
```

### §32.P3 — Reglas declaradas sin gate

Una regla cuya única aplicación es "revisión de PR" no cambia comportamiento.

*Instancia*: la regla §22 (seam de query-builder) necesitó un issue dedicado (#205) para conseguir su primera aplicación, meses después de aterrizar; ocho de nueve módulos aún no la siguen (#290). Cada regla en este archivo que realmente se sostiene — §1, §9, §20, §21, §25, §26, §27, §28 — tiene un detector AST o un ratchet shrink-only detrás.

**Criterio**: una regla nueva en este archivo envía con (a) un detector o ratchet, o (b) un baseline explícito más un deadline de adopción. Si ninguno es factible, escríbala como *preferencia* documentada y no reclame aplicación que no tiene.

### §32.P4 — Manejo de excepciones parcial

El fallo esperado se captura; el adyacente de la capa debajo se escapa.

*Instancia*: `admin_add_user` captura `ValueError` del service y deja que `InsForgeError` del transporte alcance un 500 no manejado (#277). Tampoco hay handler global de excepciones en `app/` que lo capture.

**Criterio**: cualquier route que llame a un service que alcanza InsForge maneja tanto el error de dominio como `InsForgeError` — o existe un handler global de excepciones y está testeado. Nunca amplíe a un `except Exception` desnudo para satisfacer esto; nombre los errores.

### §32.P5 — Docstrings dejados atrás por refactors

*Instancia*: el thinning de routes #233 cambió `photo_service` de streaming a buffering y dejó el docstring del módulo describiendo el viejo contrato `StreamingResponse`, incluido un paso `next(byte_iter)` que ya no existe (#285).

La regla §30 ya prohíbe esto y no lo capturó, porque el refactor tocó la *función* mientras el contrato stale vivía en el docstring *del módulo*.

**Criterio**: la comprobación de drift de §30 se extiende al docstring del módulo de cada archivo en el diff, no solo a los docstrings de las funciones que cambiaron. Si un docstring de módulo describe un flujo de datos, y el diff cambia ese flujo, el docstring es parte del diff.

### §32.P6 — Tests que existen pero nunca corren

*Instancia*: `test_voluntarios_concurrent.py` falla duro sin PostgreSQL y se `--deselect`-ea en CI, así que el único guard de regresión del fix TOCTOU no se ejecuta en ningún sitio (#282). Misma familia: el job E2E gated en un secret que no está fijado (#206, #223).

**Criterio**: ningún test puede estar simultáneamente fallando duro en la corrida local por defecto y excluido en CI. Corre en algún sitio, o es un `skip` con razón documentada y un issue enlazado. "Fallar duro, no skip" solo es diseño defendible cuando alguna pipeline satisface el pre-requisito.

### §32.P7 — Guards que se cancelan a sí mismos

Dos reglas individualmente razonables que se anulan entre sí, sin test que pinee la interacción.

*Instancia*: el job `deploy` de CI salta commits que matchean `^Merge pull request #`, mientras §15.2 hace que cada push deploy-worthy a `main` sea exactamente tal commit (#281). El paso de deploy estuvo muerto durante todo el periodo pre-MVP.

**Criterio**: cada guard condicional en `ci.yml` lleva un comentario que nombra qué eventos reales la alcanzan y cuáles se saltan, y `tests/test_ci_workflow.py` pinea la condición. Un guard que nadie puede disparar es indistinguible de un paso borrado.

### §32.P8 — Métricas agregadas ocultando gaps por capa

*Instancia*: 89.18% de cobertura global ocultó una capa de route entre 57% y 83%, con `voluntarios/routes.py` al 57.3% (#288). El suelo en `pyproject.toml` es global, así que nada se quejó.

**Criterio**: los suelos de calidad se declaran por capa, no solo en agregado. Cuando suba un umbral global, revise primero la distribución debajo y diga en el PR qué archivo es el mínimo actual.

## Aplicación

Revisión de PR, usando los criterios numerados arriba como checklist. §32.P2, §32.P3, §32.P6 y §32.P7 son las cuatro que son mecánicamente chequeables — cuando un PR añade un secret de `Settings`, una regla nueva, un test o un guard de CI, el revisor aplica el criterio correspondiente antes de aprobar. La auditoría que produjo esta regla es el issue #294; sus hallazgos llevan la label `audit-2026-07-25`.

## Core invariants

- **Perímetro primero**: cada endurecimiento interno cita su exposición de borde en una línea.
- **Secret defaults seguros**: pydantic falla o el lifespan rehúsa servir, nunca default usable.
- **Cada regla tiene gate**: detector AST, ratchet shrink-only o baseline explícito.
- **Errores nombrados**: nunca `except Exception` para esconder errores adyacentes.
- **Docstrings sincronizados**: módulo docstring también es contrato.
- **Tests que corren**: ningún test hard-failing-y-excluido; cada guard de CI pineado por test.

## Contributor checklist

- [ ] Si añade un secret a `Settings`, sigue §32.P2 — pydantic o lifespan rechaza el placeholder.
- [ ] Si añade una regla nueva, sigue §32.P3 — detector, ratchet o baseline explícito con deadline.
- [ ] Si su route llama a un service, nombra `ValueError` y `InsForgeError` explícitamente.
- [ ] Si un módulo docstring describe un flujo que cambió, lo reescribe en el mismo PR (§32.P5).
- [ ] Si añade un test con pre-requisito externo, documenta el skip con issue enlazado (§32.P6).
- [ ] Si su PR añade un guard en `ci.yml`, pinea la condición en `tests/test_ci_workflow.py` (§32.P7).
- [ ] Si sube el suelo de cobertura global, enuncia la distribución por capa y el archivo mínimo (§32.P8).

## Navigation

Previous: [Orchestrator discipline](orchestrator-discipline.md) | Next: [Code quality rules](code-quality-rules.md)
