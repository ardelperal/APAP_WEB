# ENCARGO PARA LA IA INVESTIGADORA — Ingeniería inversa del CI de `gentle-ai`

> Dá este fichero completo a la IA investigadora. Ella no necesita contexto previo de esta conversación.

---

## Misión

Investigar el sistema de CI e ingeniería del repositorio **`Gentleman-Programming/gentle-ai`** (público, maintainer: Alan / Gentleman-Programming) y producir un **informe de investigación** cuyo único propósito sea: **encontrar ideas transferibles para mejorar el CI de nuestro repositorio** `ardelperal/APAP_WEB`.

El interés no es imitar: es **aprender de un maintainer veterano** cómo organiza sus gates, sus convenciones y su automatización, y contrastarlo con nuestro patrón para hallar lo que nos falta.

## Reglas de conducta

1. **Read-only absoluto** sobre `gentle-ai`: clonalo en `/tmp/gentle-ai-research` (`git clone --depth 50 https://github.com/Gentleman-Programming/gentle-ai /tmp/gentle-ai-research`); nada de issues, PRs, stars, forks ni ninguna otra interacción con GitHub sobre ese repo. Las consultas `gh api` públicas de metadatos (runs, protection) son aceptables.
2. **No edites nada** en `ardelperal/APAP_WEB` salvo el fichero de informe indicado abajo.
3. **Cita evidencia**: cada afirmación lleva `fichero:línea` o URL de commit/issue. Distingue siempre "el workflow lo hace" de "la doc dice que lo hace".
4. Los fallos y fricciones del pasado son **tan valiosos como los diseños**: si encontrás commits de arreglo de CI, estudiá qué rompía antes.
5. No inventes: si algo no se puede verificar, va a una sección "sin verificar".

## Contexto de nuestro lado (para comparar)

Nuestro repositorio (`ardelperal/APAP_WEB`, local `apap-app`) tiene un patrón de CI propio en construcción, documentado en:

- `odd/HANDOFF-ci-2026-09-30.md` — el estado completo del esfuerzo (léelo entero primero).
- `odd/skill-ci-portable/source-notes.md` — 12+1 reglas de diseño de nuestro patrón con evidencia.
- Issue #935 de `ardelperal/APAP_WEB` (comentarios "Consolidación de fricciones del CI") — nuestro catálogo de fricciones.

Nuestro patrón, en una pincelada: gates en capas (lint ~30s con `preflight.py` canónico → test → integración → e2e), contratos mecánicos de issue/PR (`issue-spec` valida rama↔issue↔cierre), presupuesto de revisión de 400 líneas con ratchets shrink-only, binding evidencia↔SHA del deploy (smoke automático + batería manual por rutas sensibles), worktrees por unidad de trabajo y merges no-ff con ramas remotas preservadas.

## Qué investigar en `gentle-ai` (en este orden)

1. **`.github/workflows/`** — todos los workflows: triggers, jobs, capas, tiempos, qué bloquea y qué es informativo, caching, matrices, runners (hosted vs self-hosted).
2. **`AGENTS.md` / `CLAUDE.md` / `CONTRIBUTING.md`** — las reglas que Alan impone a las IAs y contribuidores: convenciones de commit, formato de issues/PRs, definición de terminado, disciplina de revisión. Cómo hace cumplir las reglas: ¿por doc, por script, por workflow?
3. **`scripts/` y `Makefile`/`justfile`** — gates mecánicos, checks locales, preflight si existe, tooling de calidad (linters custom, ratchets, inventarios).
4. **Flujo de release** — cómo publica (Go binary + npm package `gentle-pi`): versionado, tags, automatización del publish, firma, changelog.
5. **Protección de ramas y merge** — `gh api repos/Gentleman-Programming/gentle-ai/branches/main/protection` y settings del repo: strict, auto-merge, merge queue, rulesets.
6. **El historial de CI** — `gh run list -R Gentleman-Programming/gentle-ai --limit 30`: frecuencia, duración, tasa de fallo; y commits tipo `fix(ci):` para aprender de sus roturas.
7. **La relación IA-proceso** — este repo ES una herramienta para agentes de código: investigá cómo el propio Alan usa y prueba su CI con agentes (estructuras tipo skill, handoffs, contracts, prompts versionados).

## Qué entregar

Escribí el informe en:

```
/home/ubuntu/repos/apap-app/odd/skill-ci-portable/gentle-ai-ci-research-report.md
```

Estructura obligatoria del informe:

1. **Mapa del sistema** — workflows y su topología, con tiempos y capas.
2. **Convenciones del maintainer** — las reglas de Alan y cómo se hacen cumplir (doc vs script vs workflow).
3. **Gates mecánicos** — cada check: qué valida, cómo, y qué pasaría si se lo quita.
4. **Release flow** — de commit a publicación.
5. **Catálogo de ideas transferibles** — cada idea con: qué hace `gentle-ai`, qué hacemos nosotros hoy (o no hacemos), por qué la considerás mejor, y el coste estimado de adoptarla. Sé concreto: "idea + evidencia file:line + esfuerzo estimado (S/M/L)".
6. **Cosas que NO copiaríamos** — con por qué (contexto distinto, coste, o gusto).
7. **Sin verificar** — lo que no pudiste confirmar.

Criterio de calidad: si después de tu informe no podemos señalar **al menos 3 ideas concretas y accionables** que no tuviéramos, el informe no sirve. Si encontrás 10, mejor todavía.

## Entregable adicional (opcional, valorado)

Si detectás patrones que documentan la *colaboración humano-IA* del propio Alan (handoffs, prompts, contracts, skill design), distinguilos en una sección propia: son candidatas dobles (CI + colaboración) y nuestro repo también opera con agentes.
