---
name: documentation-alan-style
description: Trigger: redactar o revisar README, AGENTS, DOCS, CODEBASE-GUIDE, CONTRIBUTING, CHANGELOG, épicas o walkthroughs JSON en Castellano peninsular formal. Adaptador de locale sobre skill-style-guide + skill-creator + skill-improver (Gentleman-Programming/gentle-ai). Cargue las skills de Alan PRIMERO para estructura y Output Contract; este adaptador agrega solo la capa de idioma Castellano.
license: MIT
metadata:
  author: gentleman-programming
  version: 2.0
  last_verified: 2026-09-03
  scope: ['universal', 'docs']
  auto_invoke: ['writing human-facing documentation', 'applying castellano alan-style']
  tiers: ['universal', 'docs']
---



# Documentation Alan-style — Adaptador Castellano

> Adaptador de locale sobre las skills canónicas de Gentleman-Programming. Las reglas estructurales viven allí; este adaptador agrega solo la capa de idioma Castellano peninsular formal.

## §1 Activación

Cargue las skills de Alan **PRIMERO**:

| Skill canónica | Aporta |
|---|---|
| `skill-style-guide` (Gentleman-Programming/gentle-ai) | Estructura, frontmatter, body budget, secciones canónicas, Output Contract |
| `skill-creator` (Gentleman-Programming/gentle-ai) | Reglas para crear skills |
| `skill-improver` (Gentleman-Programming/gentle-ai) | Auditoría de skills existentes |

Después cargue este adaptador para aplicar la capa Castellano sobre la estructura de Alan.

## §2 Principio rector

> «La documentación es para quien la lee, no para quien la escribe. Un AGENTS.md que sirve de índice, un README que cabe en cinco minutos, un CODEBASE-GUIDE que ubica en treinta segundos.»

Si una IA o un humano lee un doc y no sabe qué hacer después, el doc está mal enfocado. Reorganice hasta que la respuesta sea obvia.

## §3 Cuándo invocar este adaptador

Cargue este adaptador cuando:

- Redacte el `README.md`, `AGENTS.md`, `DOCS.md`, `CODEBASE-GUIDE.md`, `CONTRIBUTING.md` o `CHANGELOG.md` de un repo en Castellano.
- Revise un PR que cambie comportamiento documentado en cualquiera de dichos archivos.
- Escriba una `epic.md` o un `walkthrough-*.json` en Castellano.
- Defina el tono de un doc nuevo (usted, anglicismos, comillas, mayúsculas tras puntuación).

No use este adaptador para:

- Reglas estructurales (eso vive en `skill-style-guide`).
- Crear o auditar skills (eso vive en `skill-creator` y `skill-improver`).
- Skills tool-facing (esas usan el idioma del dominio, no Castellano; ver §7).
- Decisiones de arquitectura o modelo de datos.
- Tutoriales paso a paso de uso (eso es `README.md`, no este adaptador).

## §4 Capa Castellano peninsular formal

### §4.1 Idioma base

Castellano peninsular formal. La segunda persona del singular y del plural es **usted** en todas sus formas. Sin conjugaciones informales regionales, sin tuteo coloquial, sin regionalismos.

### §4.2 Glosario abreviado

| Evitar | Usar |
|---|---|
| Pronombre informal de 2.ª sing. | «usted» |
| Conjugación informal -ás / -és / -ís | «-a» / «-e» / «-a» (Peninsular estándar) |
| Imperativo informal con acento final | «-e» (Peninsular formal) |
| Muletillas coloquiales | Muletillas formales (proceda, de acuerdo, terminado) |
| 1.ª persona plural cálida | 3.ª persona (el sistema, el equipo) |
| Imperativo informal con pronombre enclítico | Imperativo formal con pronombre (le adjunto, se remite) |
| Adjetivos coloquiales de aprobación | Adjetivos formales (correcto, válido) |

### §4.3 Anglicismos que se mantienen (no traducir)

`FTS5`, `scope`, `topic`, `upsert`, `soft-delete`, `hard-delete`, `drift`, `blast radius`, `kill switch`, `ratchet`, `squash-merge`, `tenant`, `WAL`, `PITR`, `kebab-case`, `spec`, `protocol`, `commit`, `merge`, `frontend`, `backend`, `template`, `placeholder`, `walkthrough`.

### §4.4 Reglas tipográficas

- Citas en prosa: «...». Sin comillas inglesas en prosa.
- Emphasis dentro de código: `"..."` o backticks.
- Mayúscula tras `¿` o `?` solo si la frase inicia tras puntuación completa.
- **Headings en ES**: sentence case. Solo la primera letra y los nombres propios van en mayúscula.
- **Headings en EN**: Title Case. Es el estándar.
- **Párrafos**: menos de doscientos caracteres. Una idea por frase.
- **Voz activa** por defecto. «Cargue la skill», no «la skill debería ser cargada».
- **Sin marketing fluff**. «Cloud autosync disabled», no «Cloud autosync will be enabled in future releases».
- **Sin emojis decorativos** en headings ni cuerpo. Excepción: tabla de labels en `CONTRIBUTING.md`.

### §4.5 Notas sobre el frontmatter

El frontmatter YAML es **prescrito** en `skill-style-guide` de Alan y en este adaptador para que `opencode`, `Claude Code` y `Cursor` puedan filtrar por `globs`. Los ejemplos canónicos de Alan lo omiten. Use YAML por defecto; omítalo solo cuando requiera coincidencia byte a byte con un AGENTS.md de Alan.

## §5 Mapping Castellano ↔ canónico de Alan

Cuando escriba secciones en Castellano, use estos nombres. Para secciones leídas por IAs que también cargan skills de Alan, el mapeo evita ambigüedad.

| Castellano (este adaptador) | Canónico (Alan) | Uso |
|---|---|---|
| `## Activación` | `## Activation` | Cuándo cargar la skill/doc |
| `## Núcleo invariantes` | `## Core invariants` | Reglas que no deben romperse |
| «Lo que es / no es» (dos H2) | `## What this is / is not` | Afirmaciones falsables |
| `## Tabla de puertas` | `## Decision Gates` | Tabla `Condición / Acción` |
| `## Antipatrones` | `## Anti-patterns` | Tabla `Síntoma / Fix` |
| `## Contrato de salida` | `## Output Contract` | Tabla `Key / Type / Description` |
| `## Revisor checklist` | `## Contributor checklist` | Lista final pre-publicación |
| `## Navegación` | `## Navigation` | Pie de páginas radiales |

## §6 Plantillas (Castellano)

Las plantillas viven en `references/templates/` y solo contienen placeholders MUST/SHOULD/MAY con un ejemplo breve por placeholder. Sin prosa narrativa.

| Plantilla | Ruta |
|---|---|
| `README.md.tmpl` | `references/templates/README.md.tmpl` |
| `AGENTS.md.tmpl` | `references/templates/AGENTS.md.tmpl` |
| `DOCS.md.tmpl` | `references/templates/DOCS.md.tmpl` |
| `CODEBASE-GUIDE.md.tmpl` | `references/templates/CODEBASE-GUIDE.md.tmpl` |
| `CHANGELOG.md.tmpl` | `references/templates/CHANGELOG.md.tmpl` |
| `epic.md.tmpl` | `references/templates/epic.md.tmpl` |
| `walkthrough.json.tmpl` | `references/templates/walkthrough.json.tmpl` |

## §7 Excepción documentada: tool-facing vs human-facing

La regla de «Castellano peninsular formal» de §4 aplica a **documentación humana** (AGENTS.md, README, walkthroughs, epics, capability docs, decisiones arquitectónicas, narrativas operacionales leídas por personas). NO aplica uniformemente a **skills tool-facing** (skills que una IA carga durante una sesión de trabajo para decidir qué herramientas invocar).

### §7.1 Por qué la excepción

El ecosistema que esas skills envuelven (Dysflow, codegraph-vba, oci, oracle-vps, access-vba, etc.) está documentado en inglés. Los identificadores no se traducen: `sync_binary`, `codegraph_explore`, `bootstrap`, `schema`, `verify_code`, `migrate_project_config`, `list_access_operations` son nombres de tools reales cuyo contrato runtime es estable.

Forzar la prosa a castellano mientras los identificadores quedan en inglés produce un híbrido que reduce la calidad de activación de la IA (los modelos asocian mejor keywords técnicos en su idioma canónico).

### §7.2 Cómo aplicarlo

| Tipo de skill | Idioma esperado |
|---|---|
| Human-facing (AGENTS.md, walkthroughs, epics, capability docs) | Castellano peninsular formal (§4) |
| Tool-facing (envuelven un runtime/tool) | Idioma del dominio (típicamente inglés) |
| Upstream (author `gentleman-programming*`) | Idioma de la fuente original, sin traducir |

### §7.3 Criterio operativo

- Skill que envuelve un runtime/tool → idioma del dominio (inglés típicamente).
- Skill narrativa para personas → Castellano peninsular formal.
- Duda → idioma del LECTOR PRIMARIO. ¿Humano o IA activando un tool? La respuesta decide.

### §7.4 Core invariant

> **Tool-facing skills: idioma del dominio. Human-facing docs: castellano alan-style. No mezclar las dos.**

## §8 Lo que este adaptador NO es

| No es | Razón |
|---|---|
| Duplicado de `skill-style-guide` | Las reglas estructurales viven allí. Un solo lugar. |
| Duplicado de `skill-creator` | Las reglas para crear skills viven allí. |
| Skill independiente | Es adaptador; necesita la base de Alan cargada. |
| Guía de Markdown genérica | El formato ya viene cubierto por las reglas de Alan. |
| Traducción literal de Alan | Es la capa de idioma sobre la estructura, no una traducción. |

## §9 Revisor checklist

- [ ] Las reglas estructurales (frontmatter, secciones canónicas, Output Contract) las verifiqué contra `skill-style-guide` de Alan, no contra este adaptador.
- [ ] La prosa está en Castellano peninsular formal (§4).
- [ ] No hay anglicismos fuera de la lista permitida (§4.3).
- [ ] Los headings en ES siguen sentence case (§4.4).
- [ ] Si el doc es tool-facing, NO apliqué Castellano (§7).
- [ ] Las secciones usan los nombres Castellano del mapping (§5) o los canónicos de Alan, no mezcla inconsistente.
