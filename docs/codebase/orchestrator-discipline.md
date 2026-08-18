[← Back to Codebase Guide](../CODEBASE-GUIDE.md)

# Orchestrator discipline

Esta página posee la regla §17 de AGENTS verbatim: el orchestrator coordina, los subagents escriben, los review lenses se corren antes de mergear, y los cambios a `AGENTS.md` y otros docs operacionales van por feature-branch + PR.

## §17 — Disciplina de orchestrator: coordinar, delegar y revisar antes de mergear

El agente que posee este archivo en el rol "orchestrator" **no es** un escritor de código ni de docs operacionales. Su trabajo es (1) hablar con el usuario, (2) reunir contexto, (3) delegar cada escritura no trivial a un subagent y (4) correr las lentes de revisión antes de que cualquier slice aterrice en `main`. Los subagents hacen el trabajo real; el orchestrator posee el contrato de que el trabajo cumple la barra de calidad del proyecto. Esta regla existe porque cada vez que el orchestrator escribió inline, duplicó lógica que un subagent debería poseer, saltó una lente de revisión, o editó silenciosamente un doc operacional que debería haber pasado por el flow feature-branch + PR de §15.5.

### §17.1 El orchestrator coordina, los subagents escriben

El orchestrator no debe hacer nada de lo siguiente inline:

- Escribir código bajo `app/`, `tests/` o `scripts/` (routes, services, schemas, helpers, tests, fixtures).
- Autorear SQL o scripts de migración bajo `app/core/migration/`.
- Editar templates bajo `templates/` ni assets estáticos bajo `static/`.
- Editar docs operacionales que gobiernen comportamiento de agente u operador: `AGENTS.md`, `docs/proceso.md`, `docs/roadmap.md`, `docs/audits/*`, `docs/runbooks/*`, `docs/uat/*`.
- Autorear issues de GitHub o descripciones de PR para trabajo que el orchestrator no ejecutó (un subagent lo hizo).

Las acciones inline permitidas del orchestrator se limitan a: preguntas clarificadoras cortas, snippets de código cortos para ilustrar intención en un prompt de delegación y correcciones pequeñas que no justifican spawnear un subagent (un typo en un docstring, un tweak de configuración de una línea ya cubierto por una regla existente). En duda: spawnear un subagent.

**Incorrecto** — orchestrator escribe un helper inline

```python
# orchestrator scratch session, "just a quick patch"
def _row_to_voluntario(row):
    return Voluntario(id=row["id"], nombre=row["nombre"])
```

**Correcto** — orchestrator delega

```text
task(subagent="sdd-apply", branch="feat/issue-130-voluntario-row-helper",
     instructions="…implement _row_to_voluntario per TDD, follow §1, §11…")
```

Cada prompt de delegación a un subagent debe incluir:

1. Los números de regla de AGENTS relevantes que el subagent debe seguir (por ejemplo, §1, §11, §14).
2. Una instrucción explícita de usar `codegraph-vba` (MCP `codegraph_explore` + CLI `codegraph`) primero antes de cualquier `Read`/`Grep`/`Glob`, según §14.
3. Una "Definición de Hecho" concreta: qué archivos deben existir, qué tests deben pasar, qué evidencia debe devolver el subagent (SHA de commit, nombre de rama, URL de PR cuando aplique).
4. Las lentes de revisión aplicables de §17.2 — el subagent debe self-revisar con `code-review-expert` antes de reportar "done"; `judgment-day` corre solo cuando el orchestrator lo lanza.

### §17.2 Lentes de revisión — ancladas al registro de skills

Antes de que cualquier slice dirigido por un subagent aterrice en `main`, el orchestrator lanza la(s) lente(s) de revisión aplicable(s) desde el registro de skills. El registro de skills en `.atl/skill-registry.md` es la **fuente de verdad** sobre qué lentes existen. no invente nombres de lentes que no estén en el registro. Si se necesita una lente futura, instálela vía el registro primero, luego actualice esta sección en un PR de seguimiento.

**Obligatoria en cada slice**: `code-review-expert` — una única lente senior que cubre SOLID, seguridad y mantenibilidad. El orchestrator lanza esta lente sobre el diff que produjo el subagent (la rama vs `main`) y lee los hallazgos antes de aprobar el merge.

**Obligatoria cuando el diff es high-stakes**: `judgment-day` — revisión dual adversarial con `jd-judge-a` y `jd-judge-b`. El orchestrator lanza esta lente ADEMÁS de `code-review-expert` cuando el diff toca cualquiera de lo siguiente:

- Autenticación, autorización, chequeos de permisos, lógica de role o role-flag.
- Manejo de secretos, flags de cookies, CSRF, ciclo de vida de sesión, PKCE/OAuth, JWT.
- Manejo de PII, exposición de datos, emisión de audit-log, redacción de logs.
- Security gates (gatekeepers, advisories de capacidad, mecanismos de override, flags de bypass, switches administrativos manuales).
- Scripts de migración, escrituras SQL crudas, fixtures que tocan datos con forma real.

Un mapa no exhaustivo de archivos que disparan automáticamente `judgment-day` (cuando se modifican, no solo se leen): `app/core/auth*`, `app/core/csrf*`, `app/core/session*`, `app/core/logging*`, `app/core/migration/`, `app/core/insforge.py` cuando se usa para escrituras, cualquier `scripts/seed*` o `scripts/backfill*`, `scripts/check_rules.py`, `scripts/pytest_plugin/coverage_gate.py`. El orchestrator debe correr `judgment-day` si el diff toca alguna de estas rutas aunque el cambio parezca cosmético.

**Incorrecto** — orchestrator mergea un fix de CSRF sin `judgment-day`

```text
# subagent: "added X-CSRFToken header check, all tests green"
# orchestrator: "looks small, merging"
```

**Correcto** — orchestrator lanza ambas lentes

```text
review-code-expert --diff main...feat/issue-122-csrf-header-check
judgment-day --diff main...feat/issue-122-csrf-header-check \
  --triggers app/core/csrf.py
```

El orchestrator lee ambos reportes, decide qué hallazgos son blocking vs informativos y devuelve un veredicto al usuario con el SHA de commit + URL de PR + hallazgos resumidos. Los hallazgos marcados BLOCKER deben abordarse antes del merge; los CRITICAL deben abordarse o ser explícitamente dispensados por el usuario; WARNING y SUGGESTION se rastrean pero no bloquean.

### §17.3 Los cambios a AGENTS.md y otros docs operacionales van por el flow feature-branch + PR

Los docs operacionales son parte del contrato del proyecto — gobiernan cómo se comporta cada agente (orchestrator, subagent, sesión futura). Editarlos inline es el mismo tipo de bypass que escribir un handler de route en `main` sin PR. El orchestrator debe tratar cualquier cambio a `AGENTS.md`, `docs/proceso.md`, `docs/roadmap.md`, `docs/audits/*`, `docs/runbooks/*`, `docs/uat/*` exactamente como un cambio de código bajo §15.5.

Concretamente, el orchestrator delega el cambio a un subagent (típicamente vía `task` con `sdd-apply` o la skill aplicable), y el subagent sigue este flow:

1. **Branch desde `main`.** El nombre de la rama sigue §15.2: `docs/<scope>` (por ejemplo, `docs/agents-rule-17-orchestrator-discipline`).
2. **Editar en la rama.** Commit único y enfocado. Conventional commit en inglés (por ejemplo, `docs(agents): add rule 17 orchestrator discipline`).
3. **Verificar localmente antes de pushear.** Corra `git diff main...HEAD -- <file>` y lea el diff completo. Corra un `grep` enfocado por typos, cross-references rotos y cualquier mención interna que referencie un ítem que el cambio se supone que añadía o quitaba.
4. **Push + abrir PR.** Título de PR en inglés, estilo conventional-commit. Cuerpo del PR: resumen libre del cambio + un enlace o referencia a la conversación que lo pidió. Use `Refs`/`Closes` solo cuando exista un issue.
5. **CI debe estar verde.** Para un PR solo-docs esto es mayormente `ruff` y cualquier chequeo liviano; el gate es "verde", no "trivial".
6. **Devuelva y mergee si §15.6 lo autoriza.** El orchestrator (y el subagent que llevó el trabajo) devuelve el SHA de commit en la rama + la URL de PR + un diff resumido. Si la autorización standing de §15.6 está en efecto Y todos los gates de §15.1 están visiblemente verdes (local + CI), el orchestrator mergea el PR a `main` él mismo, citando la URL del run de `ci.yml` en el cuerpo del merge commit. En caso contrario (revocado, dormido, gates rojos, o cualquier ítem de la lista §15.5 tocado), el orchestrator devuelve sin mergear y el usuario revisa y mergea según §15.5.

**Incorrecto** — orchestrator edita AGENTS.md inline en el chat

```text
edit(AGENTS.md)   # orchestrator session, "just adding rule 17"
```

**Correcto** — orchestrator delega a un subagent

```text
task(subagent="sdd-apply",
     branch="docs/agents-rule-17-orchestrator-discipline",
     instructions="…add §17 to AGENTS.md per user spec. Anchored to
                   code-review-expert (mandatory each slice) and
                   judgment-day (mandatory for high-stakes). §17.3
                   explicitly forbids orchestrator inline edits.
                   Follow §15.5 flow. Do NOT merge.")
```

El orchestrator puede escribir el texto de §17 propuesto en el prompt de delegación mismo (como snippet de referencia), pero el file write, commit, push y PR open deben ocurrir del lado del subagent. El orchestrator no posee esas operaciones.

**Aplicación**: una violación de §17.1 (orchestrator escribe inline) es una falla de disciplina y el trabajo debe revertirse y rehacerse vía un subagent en una rama. Una violación de §17.2 (saltarse una lente obligatoria en un diff high-stakes) es un merge blocker — el merge no puede proceder sin el sign-off de la lente. Una violación de §17.3 (orchestrator edita `AGENTS.md` u otro doc operacional inline) es lo mismo que una violación de §15.5: el cambio debe revertirse y re-aterrizarse por el flow correcto, y el orchestrator debe reconocer el resbalón antes de continuar.

## Core invariants

- **Coordinar, no escribir**: el orchestrator nunca escribe código, SQL, templates ni docs operacionales por sí mismo.
- **Subagent-driven**: cada escritura no trivial pasa por un subagent vía `task` con Definición de Hecho explícita.
- **Code-review-expert obligatoria**: cada slice la corre antes de mergear.
- **Judgment-day en high-stakes**: auth, secrets, CSRF, PII, migration, raw SQL — siempre doble lente.
- **AGENTS.md va por PR**: cualquier cambio al doc operacional va por feature-branch + PR, nunca inline.
- **Revocable**: el usuario puede revocar la autorización de merge standing con una frase.

## Contributor checklist

- [ ] El orchestrator delega cada escritura no trivial vía `task` con DoD explícito.
- [ ] Cada prompt de delegación nombra las reglas AGENTS aplicables e instruye `codegraph_explore` primero.
- [ ] Cada slice dirigido por subagent corre `code-review-expert` antes de reportar done.
- [ ] Cada diff high-stakes corre `judgment-day` además de la lente senior.
- [ ] Ningún cambio a `AGENTS.md` o `docs/proceso.md` se hace inline en sesión del orchestrator.

## Navigation

Previous: [Merge workflow](merge-workflow.md) | Next: [Anti-patterns](anti-patterns.md)
