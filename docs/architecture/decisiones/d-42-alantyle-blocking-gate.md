# D-42 — Linter check_alantyle promovido a gate bloqueante

## Decision

A partir del merge del PR que introduce este ADR, el step `check_alantyle` del job `lint` en `.github/workflows/ci.yml` deja de usar `continue-on-error: true` y se vuelve `required`. Cero violaciones ALAN00x en `docs/`, `openspec/specs/`, `openspec/changes/*/specs/`, `README.md`, `AGENTS.md`, `DOCS.md` y `CONTRIBUTING.md` bloquea el merge.

El ADR d-42 documenta la primera generación del rollout con `continue-on-error: true`; este documento lo sustituye en favor del gate duro. El issue #578 expandió después el scope a los delta-specs de cada change (`openspec/changes/*/specs/`) y corrigió dos falsos positivos estructurales del detector (ver «Expansión de scope #578» abajo).

## Quick path

Si su PR acumula una violación ALAN00x, corra `python3 scripts/check_alantyle.py docs/ openspec/specs/ openspec/changes/*/specs/ README.md AGENTS.md DOCS.md CONTRIBUTING.md` localmente antes de pushear. Las tres vías de fix son, en orden de preferencia:

1. Reemplazar el literal por su forma minúscula cuando sea emph legítimo en prosa.
2. Mover el literal a un code fence cuando sea un identificador técnico.
3. Añadir `<!-- alantyle-ignore:ALAN00x -->` al final de la línea solo cuando las vías anteriores rompen el contexto (por ejemplo, SQL en prosa o un identificador heredado de Access que el lector necesita ver de la forma original).

## Problem statement

El rollout del linter (PRs #568, #571, #573, #575) bajó el contador de ALAN003 de 3574 a 368 violaciones en cuatro iteraciones. El step del job `lint` estuvo con `continue-on-error: true` desde el PR inicial del rollout porque activarlo como gate duro en ese punto habría bloqueado cada PR abierta por ruido informativo no relacionado con el cambio. El propio ADR d-42 advertía que la bandera se quitaría cuando el contador llegara a un valor que el equipo aceptara mantener.

## Evidence and scope

- 368 → 0 violaciones ALAN003 tras este PR (la ejecución del CI sobre `docs/ openspec/specs/ openspec/changes/` más los cinco archivos raíz reporta `OK (170 archivos)`).
- Cero ALAN001, ALAN002, ALAN004, ALAN007, ALAN009 en el mismo scope; los cinco frontmatter de los docs heredados reciben los campos obligatorios de la skill §10.
- Whitelist final estructurada en siete categorías documentadas en el script (`SQL/DB`, `HTTP/security`, `Cloud/infrastructure`, `Languages/tools`, `Quality/status`, `APAP_WEB domain`, `Repo internal`); cada entrada lleva un comentario de categoría.
- 458 directivas `<!-- alantyle-ignore:ALAN003 -->` (y 75 directivas equivalentes para ALAN002/ALAN004/ALAN007) en los docs donde el lowercase rompería la lectura del identificador (SQL en prosa, nombres heredados de Access, prefijos de tickets y de CI).

## Options considered

### Opción A — whitelist agresiva + ignore directives selectivas (aceptada)

**A favor**: baja el contador a cero sin reescribir cientos de páginas de docs legacy.

**En contra**: la whitelist crece a 442 entradas (61 de ellas ya documentadas en el primer rollout) y los comentarios de justificación deben añadirse al script.

### Opción B — rewriting completo de los docs preexistentes

**A favor**: deja el árbol sin dependencias de directivas de excepción.

**En contra**: demasiado trabajo para un PR; muchos docs no aportan valor al lector cambiado de mayúsculas a minúsculas.

### Opción C — linter opt-in (rechazada)

Mantener el step sin verificación obligatoria.

**A favor**: cero fricción.

**En contra**: el linter pierde su propósito de forzar el rigor; el rigor se queda como acuerdo verbal.

## Goals

- Bloquear merges con anti-patrones §10 de la skill `documentation-alan-style`.
- Mantener la whitelist categorizada con justificación por entrada.
- Mantener el costo de mantener directivas `alantyle-ignore` en cero o cerca de cero cuando un autor de docs puede resolver la violación con minúsculas.

## Non-goals

- Cobertura 100% de aliases tipográficos (la whitelist no es exhaustiva: cada nueva categoría de dominio exige una decisión editorial humana antes de ampliar la lista).
- Reescritura de los docs preexistentes para bajar la dependencia de directivas.
- Cobertura exhaustiva de ALAN005, ALAN006 y ALAN008 (sus contadores estaban en cero antes del rollout y el script no los cambia).

## Non-negotiable invariants

- Cada nueva entrada de la whitelist lleva el comentario `SQL/DB`, `HTTP/security`, `Cloud/infrastructure`, `Languages/tools`, `Quality/status`, `APAP_WEB domain` o `Repo internal` junto al término. Una entrada sin categoría es la regresión que el code-review rechaza.
- Las directivas `<!-- alantyle-ignore:ALANxxx -->` se admiten solo cuando el lowercase rompería la lectura del identificador (SQL en prosa, nombres heredados de Access, prefijos de tickets y de CI). Cualquier otro uso es una señal para arreglar el doc.
- El step `check_alantyle` permanece en el scope declarado en el comentario del job `lint`: `docs/`, `openspec/specs/`, `openspec/changes/*/specs/` más los cinco archivos raíz. Mover el scope es decisión editorial humana, no de este PR.

## Consequences

**Cambia**: el step `check_alantyle` ya no admite `continue-on-error: true`. Cualquier ALAN00x en los paths declarados falla el job `lint` y bloquea el merge.

**Cambia**: la whitelist se reorganiza en siete categorías documentadas con comentarios a la derecha del término; las entradas nuevas pasan por ese comentario, no por la lista plana previa.

**Cambia**: cinco docs heredados reciben frontmatter completo (`name`, `description`, `license`, `metadata.author`, `metadata.version`) por demanda de ALAN001; sus títulos literales se mueven a `title:` para no romperlos.

**No cambia**: las reglas §10 de la skill, los contadores existentes, los nueve códigos ALAN00x ni el comentario que documenta el scope del step.

## Expansión de scope #578

El issue #578 incorporó los delta-specs de cada change (`openspec/changes/*/specs/`) al gate. Hacerlo viable exigió tres cambios en el detector, todos cubiertos por tests en `tests/test_check_alantyle.py`:

- **Inline-code masking**: los spans `` `...` `` se reemplazan por espacios de igual longitud antes de los detectores de prosa (ALAN003, ALAN004, ALAN007). Las queries SQL e identificadores dentro de backticks ya no disparan falsos positivos; las columnas reportadas siguen coincidiendo con la línea cruda.
- **Whitelist spec-context**: los archivos bajo `openspec/` usan un frozenset independiente (`_SPEC_CONTEXT_KEYWORDS`) con las keywords RFC 2119 (`MUST`/`SHALL`/`SHOULD`/`MAY`/`NOT`), los marcadores BDD (`GIVEN`/`WHEN`/`THEN`) y el vocabulario de escenario en castellano (`DEBE`/`YA`/`DOS`/`PASA`/`FALLA`, etc.). Esas palabras son lenguaje semántico de spec, no emph editorial. El guardrail `test_whitelist_v2_does_not_relax_emph_words` sigue protegiendo `docs/`: fuera de `openspec/` esas mismas palabras se reportan.
- **Exclusión de `archive/`**: `openspec/changes/archive/` queda fuera del scan (`_EXCLUDED_DIR_SEGMENTS`). Son cambios cerrados, registros históricos inmutables que no deben re-editarse para satisfacer el linter.

Los artefactos de trabajo `proposal.md`, `design.md`, `tasks.md` y `exploration.md` de cada change permanecen fuera del scope (solo se gatean los `spec.md` bajo `specs/`), igual que `archive/`.

## When this changes

- Se introduce una nueva categoría de dominio en el repo (ej: integración con un SaaS cuyas siglas aparecen en prosa): añadir las siglas a la whitelist bajo la categoría `Cloud/infrastructure` o `Languages/tools` con el comentario que justifique el alcance.
- La skill `documentation-alan-style` evoluciona (§10 sigue creciendo): actualizar el script con el nuevo detector antes de revertir este ADR.
- Aparece un nuevo ALAN00x que reporta positivo en CI: abrir PR que justifique su whitelist o ignore directive siguiendo el patrón de este ADR.
