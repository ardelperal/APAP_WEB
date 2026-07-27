# Decisiones de proyecto — APAP_WEB

> Registro canónico de decisiones de producto, UX, arquitectura y proceso. Cualquier "esto es así porque X" tiene que estar aquí. Si una decisión contradice el código o la doc, gana el código y este doc se actualiza en la misma sesión (ver `docs/proceso.md` P3 y `docs/roadmap.md` §9).

**Última actualización:** 2026-07-27 (añadida D-25 sobre librería de fuzzy match para VOL-03 issue #36: `rapidfuzz` en lugar de `thefuzz`)
**Mantenedor único:** aroman (ver D-36)

---

## §1. Producto

### D-01. APAP_WEB es un producto profesional standalone

APAP_WEB no es una migración de UI del Access legacy. Es una aplicación profesional, server-rendered (FastAPI + HTMX + Jinja2), usable y presentable a stakeholders, voluntarios, adoptantes y al público general. El Access legacy es la fuente de reglas/datos/workflows pero NO la fuente de UX.

**Origen:** #130 docs(product), issue abierta 2026-06-28.

### D-02. Home = dashboard con tarjetas de pendientes operativos

La página principal (`/`) muestra tarjetas con pendientes operativos: entradas recientes, voluntarios, animales, próximos seguimientos. Sigue el patrón descrito en `docs/legacy-initial-dashboard.md`, modernizado a un patrón "bandeja de pendientes" con realtime en una segunda iteración.

**Origen:** #130 + issues cerradas #127 (home con tarjetas), #131 (labels castellanos).

### D-03. Dominio centrado en Animal

Animal es la entidad pivotante. Fichas, timeline, salud, terapias, contratos y adopciones cuelgan de él. Esto refleja la operativa real de la protectora y la estructura del legacy.

**Origen:** #130 + `docs/discovery/feature-01-animal-lifecycle.md` + `docs/legacy-lifecycle-transition-rules.md`.

### D-04. Paridad de campos del animal con el Access legacy

El modelo `animal` (tabla y formulario) del sistema nuevo tiene paridad de campos obligatorios con el Access legacy, según `docs/discovery/data-model-completeness.md`. Cualquier gap entre campos legacy y campos nuevos es un `type:bug` con label `gap:legacy` (ver D-05 y `docs/proceso.md` §4.6).

**Origen:** #129 fix(animals) — alinear campos obligatorios de ficha con Access y discovery.

### D-05. Fidelidad al legacy = superset funcional (Premisa P1)

El sistema nuevo debe poder sincronizarse con el Access/VBA legacy preservando el **100% de las intenciones y funcionalidades del legacy**, más las funcionalidades nuevas acordadas en `docs/roadmap.md` §3 (Fases 3-7 + transversales) y `docs/discovery/`. Ni una menos.

- Trazabilidad por capacidad legacy: capability legacy → su representación en el modelo nuevo → cobertura de tests.
- Cualquier gap descubierto en el nuevo modelo es `type:bug` con label `gap:legacy`.

**Origen:** reafirmado por el usuario el 2026-07-03. Codificado en `docs/proceso.md` §0 P1.

---

## §2. UX y visual

### D-10. Idioma visible en UI: castellano de España

Todos los labels, mensajes y textos visibles al usuario final en castellano de España (tildes, ñ, vocabulario peninsular). Esto afecta solo a la UI; los identificadores internos (nombres de campos, nombres de variables, contratos JSON) permanecen en inglés (D-37).

**Origen:** issues #127, #128, #131 — todo el trabajo de copy/UI reciente.

### D-11. No clonar la UX del legacy

El Access legacy tiene una UX específica que NO se replica. La nueva UI usa los mismos datos y reglas, pero con un patrón moderno: componentes reutilizables, sistema de diseño, navegación clara. Ver `docs/legacy-initial-dashboard.md` y `docs/legacy-health-ui-workflow.md` solo como referencia de QUÉ hace el legacy, no de CÓMO se ve.

**Origen:** #130 + transversal UX/UI pendiente (#6).

### D-12. Design system reutilizable

Pendiente de issue #6 ("feat(ux): definir la base UX/UI de APAP"). Hasta que se implemente, la UI se construye con tokens ad-hoc heredados de `docs/design-tokens-apap-actual.md` (referencia del legacy).

---

## §3. Arquitectura y stack

### D-20. Stack base: FastAPI + HTMX + Jinja2 + InsForge

- **Backend**: FastAPI + Pydantic, sin ORM (DAO directo a InsForge vía httpx en `app/core/insforge.py`).
- **Frontend**: HTMX + Jinja2 server-rendered + Tailwind v4.
- **Backend BaaS**: InsForge (Postgres + auth + storage) — accedido desde Python, no desde el SDK TS (el proyecto no tiene `package.json`).
- **Auth**: Google OAuth vía InsForge (`exchange_insforge_oauth_code`) + allowlist en tabla `authorized_users`.
- **Despliegue**: Coolify + Dockerfile, webhook en `push` a `main` (D-30).

Detalle completo en `docs/architecture-insforge-stack.md` *(pendiente de traducir al castellano)*.

### D-21. CodeGraph es el read path principal

CodeGraph (`@aroman22/codegraph-vba` CLI + MCP `codegraph_explore` + `codegraph node`) es la herramienta canónica de lectura de código. `Read`/`Grep`/`Glob` solo cuando codegraph no llega. El daemon auto-sync cubre el crecimiento del codebase con ~1s de lag; las sesiones nuevas empiezan con `codegraph status .` + `codegraph daemons` para confirmar salud.

Detalle completo en `AGENTS.md` §14 y `docs/proceso.md` §1.

**Origen:** establecido 2026-07-03.

### D-24. Regla de validación de fechas en actuaciones sanitarias

La `fecha` de una `actuacion_sanitaria` debe cumplir simultáneamente:

1. **Formato ISO `YYYY-MM-DD`** parseable como `date`.
2. **`fecha <= CURRENT_DATE`** del servidor (no se permiten fechas futuras).
3. **Si el animal referenciado tiene `fecha_alta IS NOT NULL`, `fecha >= animales.fecha_alta`** (no se permiten fechas anteriores al alta del animal en el sistema).

Si el animal tiene `fecha_alta IS NULL` (animales legacy importados sin metadato), la cota inferior de la regla 3 se omite — solo se aplican las reglas 1 y 2.

**Implementación en dos capas** (`app/modules/sanidad/service.py`):

- **Validación pura (sin DB)** en `_validate_fecha_d24(fecha)` corre ANTES del INSERT/UPDATE: parsea la fecha, rechaza futuro y malformado con mensaje castellano (reglas 1+2).
- **Validación atómica con CTE** en `_INSERT_ACTUACION_SANITARIA_SQL` y `_UPDATE_ACTUACION_SANITARIA_SQL`: el `checked_animal` filtra `WHERE id = $1 AND activo = true AND (fecha_alta IS NULL OR fecha_alta::date <= $3::date)`. PostgreSQL evalúa el check FK + fecha_alta bajo el mismo snapshot, cerrando la ventana TOCTOU entre el SELECT y el write (regla 3).
- **Disambiguation** en `_raise_validation_error` re-ejecuta la query con `SELECT id, activo, fecha_alta FROM animales WHERE id = $1` cuando la CTE devuelve 0 filas, para emitir el mensaje específico ("fecha es anterior al alta del animal (YYYY-MM-DD)" vs "animal inactivo" vs "voluntario inactivo" vs "tipo de prueba inexistente").

**Por qué no más restrictivo** (p. ej. no anterior a `animales.FNacimiento`): el refugio a veces registra vacunas administradas antes del alta del animal (p. ej., camadas con cachorros ya vacunados por el particular). El `fecha_alta` es el límite inferior porque refleja cuándo APAP tiene constancia del animal, no cuándo nació.

**Origen:** issue #50 (HEALTH-01, Fase 6a). Regla referenciada en `docs/roadmap.md` §3 desde la planificación inicial pero sin definición operativa hasta este slice. Implementación verificada por 5 átomos TDD específicos en `tests/test_sanidad.py` (reglas 1+2 puras + regla 3 atómica + exención NULL).

### D-25. Librería de fuzzy match para VOL-03: `rapidfuzz` (no `thefuzz`)

El pipeline de deduplicación fuzzy de voluntarios legacy (issue #36 / VOL-03) usa `rapidfuzz` (`>=3.0`, current stable 3.14.x) en vez de `thefuzz` (formerly `fuzzywuzzy`).

**Por qué `rapidfuzz` y no `thefuzz`:**

- `thefuzz` está efectivamente abandonado: último release `0.22.1` del 2024-01-19, sin commits en los últimos 90 días (repositorio `seatgeek/thefuzz` 2026-07-25).
- `rapidfuzz` es su sucesor mantenido por el mismo autor (`maxbachmann`): release `3.14.5` del 2026-04-07, wheels precompilados para Python 3.10+, implementación C++ que evita la capa Python de `thefuzz` (10–50× más rápido en benchmarks).
- AGENTS.md §8 prohíbe pinear librerías deprecadas; `thefuzz` entraría en esa categoría.

**Contrato de la API usado**: `rapidfuzz.fuzz.WRatio` (weighted ratio, accent- y case-insensitive) combinado con pre-normalización de diacríticos vía `unicodedata.normalize("NFKD", ...)` + filtrado de `unicodedata.combining(ch)`. La pre-normalización es necesaria porque `WRatio` por sí solo puntúa "María García" / "Maria Garcia" en 83 (por debajo del threshold 85); con la normalización previa la puntuación sube a 100.

**Threshold por defecto**: 85 (sobre la escala 0..100 de `rapidfuzz`). Configurable por el caller (`dedup_volunteers(refs, fuzzy_threshold=N)`); el default es lo bastante alto para evitar colisiones accidentales con nombres no relacionados y lo bastante bajo para absorber typos y variantes de diacríticos comunes en el legacy.

**Origen:** issue #36 (VOL-03, `legacy-discovery-interregatorio` task 3.2), issue spec nota "Considerar thefuzz (formerly fuzzywuzzy) — validar via Context7" — validado en sesión 2026-07-27 vía context7 MCP `resolve-library-id` + `query-docs` + `websearch` (estado de mantenimiento de `seatgeek/thefuzz`).

---

## §4. Proceso y entrega

### D-30. Pre-MVP single-branch workflow

Hasta que se alcance MVP, todo va a `main` directamente. Una sola rama al final de cada ciclo. No se crea ni se persiste `staging` en pre-MVP. Las issues cerradas se cierran con trazabilidad obligatoria (SHA + test path).

La reversión post-MVP está documentada en `AGENTS.md` §15.4 y se activa solo con instrucción explícita del usuario ("ya tenemos MVC" / equivalente).

**Origen:** establecido por el usuario el 2026-07-03. Codificado en `AGENTS.md` §15 y `docs/proceso.md` P4.

### D-31. Resolución de dudas del dominio en orden fijo (Premisa P2)

Cuando algo no queda claro (modelo de datos, regla de negocio, comportamiento esperado, edge case):

1. `docs/discovery/feature-XX-*.md` (versión revisada)
2. `docs/decisiones-proyecto.md` (este doc)
3. `docs/legacy-<área>.md` (legacy documentado)
4. **El Access directamente vía Dysflow MCP** (`projectId: apap`) — `dysflow_list_tables`, `dysflow_get_schema`, `dysflow_get_relationships`, `dysflow_query_sql` (read), `dysflow_count_rows`.

Solo `vba-access` y `access-vba-tdd` están permitidos como skills para Access. Los demás skills de Access (`access-vba-sync`, `access-query`, `access-form-creation`, `access-sandbox`) están excluidos del workflow de APAP_WEB.

Si tras las 4 capas la duda persiste: **preguntar al usuario**, no asumir.

**Origen:** `docs/proceso.md` P2 + `docs/roadmap.md` §7.

### D-32. Documentación refleja código (Premisa P3)

La doc (incluido este `decisiones-proyecto.md` y `docs/roadmap.md`) **refleja** el código, no al revés. Si divergen, gana el código. La actualización de la doc ocurre en la misma sesión en que se detecta la divergencia. Esto no es opcional — ver `docs/roadmap.md` §9.

### D-33. TDD estricto

Tests antes de código (excepto `type:docs` y ops puros). Cada unidad de trabajo = 1 issue → test rojo → implementación mínima que lo pone en verde → refactor con tests verdes → integrar → cerrar issue con trazabilidad (commit SHA + test path).

`pytest -W error::DeprecationWarning` corre verde en todo momento. CI gate en `ci / test`.

**Origen:** regla histórica del proyecto.

### D-34. Conventional Commits en inglés

`tipo(scope): subject` en inglés, scope corto (`feat(auth)`, `fix(animals)`, `test(copy)`, `docs(roadmap)`, `chore(deps)`). Body que referencia la issue (`Closes #N` o `Refs #N`). PRs grandes: el cuerpo del commit incluye el run URL del CI que probó verde.

### D-35. Presupuesto de revisión: 400 líneas por PR

Si la diff supera 400 líneas, dividir en PRs encadenadas vía skill `chained-pr` (default `stacked-to-main` en pre-MVP, dado que solo hay una rama).

### D-36. Mantenedor único: aroman

aroman autoaprueba issues y PRs del proyecto. Documentado en `docs/roadmap.md` §1.

### D-37. Convenciones de idioma

| Ámbito | Idioma |
|---|---|
| Issues y PRs | Castellano (España) |
| Documentación de producto, arquitectura y SDD | Castellano (España) |
| Artefactos técnicos (código, comentarios, docstrings, nombres) | Inglés por defecto |
| UI labels / mensajes visibles al usuario | Castellano de España (D-10) |
| Memoria interna / commit subjects | Inglés |

**Origen:** regla histórica, decisión del 2026-06-17.

### D-38. `git config gentleai.stagingOnly` está unset en este repo

El flag `gentleai.stagingOnly` se desactivó para APAP_WEB el 2026-07-03 (D-30, pre-MVP). El pre-push hook global sigue activo para otros proyectos. NO re-armar en pre-MVP. Re-armar solo en el flip post-MVP per `AGENTS.md` §15.4.

---

## §5. UAT y validación

### D-40. Virginia como validadora UAT (post-MVP)

Cuando llegue el MVP, Virginia corre la validación UAT sobre `staging` usando el skill `feature-acceptance-uat` (`docs/uat/uat-staging-<YYYY-MM-DD>.html`). El usuario revisa el sign-off y explícitamente instruye "merge to main". El agente NO preemptivamente flipea la fase — espera el OK explícito.

**Origen:** mencionado por el usuario el 2026-07-03; ya estaba en la regla global `staging-acceptance-contract`.

### D-41. Trazabilidad obligatoria al cerrar issues

Cada `gh issue close #N` incluye:
1. SHA(s) del commit de implementación (verificable con `git merge-base --is-ancestor <sha> main`).
2. Referencia al test que prueba el cumplimiento (path del módulo + nombre del test).
3. PR referencia.

Ver `docs/proceso.md` §6.3 y la regla global `github-issue-closure-traceability`.

---

## §6. Decisiones heredadas del legacy (resumen)

Estas decisiones las heredamos del comportamiento del Access legacy. Cada una tiene su documentación detallada en `docs/legacy-*.md` + `docs/discovery/feature-XX-*.md`.

| Capacidad legacy | Doc | Estado en modelo nuevo |
|---|---|---|
| Estados del animal + transiciones | `legacy-lifecycle-transition-rules.md`, `discovery/state-machines.md` | 🟡 pendiente, Fase 4 |
| Roles de voluntario | `legacy-volunteer-roles.md` | 🔲 pendiente, Fase 5 |
| Flujo de contratos firmados | `legacy-signed-contract-flow.md` | 🔲 pendiente, Fase 7 |
| Workflow de salud / pruebas periódicas | `legacy-health-ui-workflow.md`, `discovery/feature-03-health-care.md` | 🔲 pendiente, Fase 6 |
| Dashboard inicial con pendientes | `legacy-initial-dashboard.md` | ✅ migrado a `/` (#127, #131) |

(Por completar — esta tabla se amplía en próximas sesiones.)

---

## §7. Cómo añadir una nueva decisión

1. **Abre issue `type:docs`** con la pregunta que la decisión responde. Background + criterios + opciones consideradas.
2. **Discute en la issue** con stakeholders hasta convergencia. Cierra la issue con la decisión.
3. **Edita este doc** en la misma PR/sesión, formato `### D-XX. <título>` con:
   - Decisión concreta (qué se decide, no solo contexto).
   - **Origen**: referencia a issue(s), fecha, autor.
   - Si contradice una decisión previa, marcar la antigua como "**SUPERSEDED por D-YY**" (no borrar).
4. **Si la decisión afecta código o roadmap**, sincroniza en la misma PR (per P3 y roadmap §9).
5. **No borres decisiones históricas.** El registro es auditable.

## §8. Cómo revisar este documento

- En cada refresh del `docs/roadmap.md`, cruzar referencias con este doc y viceversa.
- Cuando una decisión quede obsoleta por código real, abrir PR de actualización (no borrar).
- Si una decisión aquí contradice lo que dice el código, **gana el código** y este doc se actualiza en la misma sesión.