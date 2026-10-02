# HANDOFF — gobierno issue→merge y skill `ci-pattern` portable (sesión 2026-10-01)

Léalo entero antes de tocar nada. Está escrito para retomar sin la conversación original.
Fecha de corte: 2026-10-01 ~17:40 UTC.

- Repositorio auditado: `ardelperal/APAP_WEB` (directorio local `apap-app`), `main` = `bdff7df` en el momento de la auditoría.
- Repositorio donde vive la skill: `DysTelefonica/team-skills` (directorio local `~/personal-skills`), `main` = `9905871`.
- Handoff anterior, todavía válido para el contexto del CI: `odd/HANDOFF-ci-2026-09-30.md`.

## 0. Objetivo y órdenes vigentes del usuario

- **Misión:** usar la auditoría del gobierno issue→merge de APAP_WEB para mejorar la skill que lo gobierna (`ci-pattern`) y hacerla **portable**. La skill vive en `team-skills` y llega a los repos de tipo `web` por propagación.
- **Autorización vigente para la ola de `team-skills`** (palabras del usuario: «sí, ve por ese camino y mergea cada PR en verde»): trabajar las issues en el orden de la #144, un PR por issue, y **fusionar cada PR cuando su CI esté verde, sin preguntar**. La graduación va la última, con dispensa.
- **Lo que no está preautorizado:** el consentimiento de la revisión nativa (`gentle-ai review`) se pide **por candidato**; hay que transmitir el sobre de consentimiento al usuario cada vez. Las dos veces de esta sesión respondió «Revisar este cambio».
- **Autorización permanente en APAP_WEB:** todo hallazgo de CI se abre directamente con `status:approved` + `ci-audit-2026-09-24` bajo la épica #935. No cubre `team-skills`.
- **Reglas del usuario** (`~/.claude/CLAUDE.md`): commits convencionales sin atribución de IA; `bat/fd/rg/sd/eza`, nunca `cat/grep/find/sed/ls`; respuestas cortas; una pregunta cada vez y esperar; verificar antes de dar la razón; rioplatense con el usuario, artefactos técnicos en inglés, documentos del repo en castellano formal; nunca borrar una rama remota.
- **Principio que el usuario repite:** segunda ocurrencia de un defecto ⇒ arreglo de causa raíz, no otro parche.

## 1. Qué está hecho

### 1.1 Auditoría (solo lectura)

Auditoría del camino issue→merge de APAP_WEB sobre `bdff7df` y el estado vivo de GitHub. El resumen completo está en Engram, tema `audit/ci-issue-to-merge-2026-10-01`. Datos vivos que conviene recordar:

- Protección de `main`: tres contextos requeridos (`branch-name`, `required`, `pr-size / pr-size`), `strict` y `enforce_admins` activos, 0 aprobaciones, resolución de conversaciones desactivada. Ruleset `main-maintainers-and-admins-merge` **deshabilitado**. El host permite squash y rebase aunque la política es merge-only.
- Últimos 60 PRs fusionados: los 60 abiertos y fusionados por la misma cuenta, 20 por encima de 400 líneas, 35 sin etiqueta `type:*`, ninguna revisión humana (las 3 «reviews» son comentarios de un bot).

### 1.2 Ola de APAP_WEB (creada, sin implementar)

| Issue | Tema |
|---|---|
| #1174 | `required` ignora un job de `needs` ausente de `ALL_JOBS` (latente: hoy 13 = 13) |
| #1175 | Deriva docs↔host |
| #1176 | La auditoría de `main` no detecta un push directo |
| #1177 | Run manual o de tag publica checks requeridos en verde sin evaluar |
| #1178 | Gate dormido devuelve 0 aunque no haya corrido |
| #1179 | `branch-name` rechaza la rama de Revert y ecosistemas de Dependabot |
| #1180 | Baselines y policy comparadas solo contra la copia del PR (solapa con #1107) |
| #1181 | La allowlist «no-UI» exime al e2e de sus propios tests |
| #1182 | `SECURITY.md` con correo no entregable |
| #1183 | Lentes de revisión no verificables |
| #1184 | 20 de 69 issues aprobadas no pasan el contrato de spec |
| #1185 | `pip-audit` por PR falla en ramas que no tocan dependencias |

Comentarios con evidencia nueva en #1122 (verde rancio) y #1127 (exenciones por prefijo), y resumen en #935 y #1129. Todas las nuevas llevan `status:approved` + `ci-audit-2026-09-24`.

**#1179 ya no es latente:** el PR #1186 (`dependabot/uv/gitpython-3.1.62`, 2026-10-01 17:25 UTC) tiene `branch-name` en `FAILURE`. Quedó comentado en la issue. Ese PR no puede fusionarse hasta corregir el patrón.

Sin probar en vivo, y así consta en cada issue: #1177 (que GitHub acepte los checks de un run manual para un PR abierto) y el escenario de #1122.

### 1.3 Ola de `team-skills` (creada y aprobada)

Issues #131–#143 más la de seguimiento #144, todas con `status:approved` (aprobación explícita del usuario en esta sesión). La #142 está cerrada (ver 1.4) y su casilla S13 tildada en la #144.

### 1.4 Entregado en `team-skills` `main`

- **PR #146 → `ca640a3`.** El validador de frontmatter comprueba el prefijo `Trigger:` sobre el valor sin comillas. Causa raíz de un fallo que ya había aparecido tres veces: una descripción con `: ` solo es YAML válido entre comillas.
- **PR #145 → `9905871`.** Arreglo de `skills/skill-propagation/assets/graduation-helper.sh` (resolvía la raíz un nivel de más y salía siempre con exit 2; el reuso solo conocía rutas de Windows) y **dispensa de estabilidad como dato** en `personal/graduation-waivers.tsv`. Skill `skill-propagation` en 0.4. Cierra #142.
- CI de `main` en `9905871` (run 36899069560): `smoke`, `unit` y `full` en verde.
- Los dos cambios pasaron la revisión nativa de cuatro lentes (aprobada y con acuse).

Cómo se usa el gate: fila en `personal/graduation-waivers.tsv` (cinco columnas separadas por tabulador: `skill`, `reason`, `authorized_by`, `granted`, `expires`; como máximo 30 días entre las dos fechas), ejecutar el helper **desde el repo**, y con `PASS-WITH-WAIVER` mover la carpeta a `skills/`. Solo dispensa la estabilidad; calidad y reuso no se dispensan. En Linux: `GRADUATION_REUSE_ROOTS=$HOME/repos` (es también el valor por defecto).

## 2. Trabajo commiteado y sin entregar en el momento del corte

**T0 — mejoras al helper surgidas de la revisión.** Worktree `~/personal-skills-worktrees/graduation-helper-review-followups`, rama `fix/graduation-helper-review-followups`, base `9905871`. **Commit `d30f075`** (`fix(skill-propagation): trace forced date and match waiver rows by exact column in graduation-helper`), árbol limpio, **sin push, sin revisión nativa, sin PR**. 181 líneas añadidas y 30 borradas en tres archivos.

Qué hace:

- Con `GRADUATION_TODAY` definida, imprime un `AVISO:` con la fecha forzada y la real, y añade ` [fecha forzada: AAAA-MM-DD]` a la línea de veredicto. Los códigos de salida no cambian.
- La fila de dispensa se elige por igualdad exacta de la primera columna separada por tabulador. Una fila cuya primera palabra es la skill pero cuya columna no coincide exactamente (espacios en vez de tabuladores, espacio antes o después, palabra extra) es `waiver_invalid`.
- `GRADUATION_REUSE_ROOTS` definida pero vacía falla el reuso en vez de caer a los valores por defecto.
- La suite usa un autorizante y fechas que no aparecen en ningún otro punto de la salida. `skill-propagation` pasa a 0.5.

Evidencia: antes del arreglo, 132 aprobados y 27 fallidos; después, 159 y 0 (re-ejecutado por la sesión que escribe este handoff). Validador de frontmatter, `bash -n`, suite i18n y `shellcheck` en verde.

Dos decisiones del escritor que el usuario no ha visto y conviene mencionarle al entregar:

1. Bajo fecha forzada el helper **sigue imprimiendo los pasos manuales** de graduación, con el veredicto marcado. Suprimirlos haría imposible probar el camino `PASS-WITH-WAIVER`.
2. La HR-8 de `skill-propagation` dice ahora que un veredicto marcado «MUST NOT tomarse como evaluación real del gate». Es la lectura del escritor del encargo.

Para entregarlo: ciclo de la sección 4 desde el paso 3 (evaluar riesgo, revisión con consentimiento del usuario, push, PR, CI, merge en verde). No tiene issue propia; es seguimiento del PR #145, así que el PR no lleva `Closes`.

## 3. Lo que falta

Plan detallado y casillas: `~/personal-skills/odd/tasks/ci-pattern-portable-wave.md` (espejo en Engram, tema `odd/ci-pattern-portable-wave/tasks`). Orden obligatorio, **en serie** porque todas las issues editan las mismas secciones de `personal/ardelperal/ci-pattern/SKILL.md`: cada PR se fusiona antes de cortar la rama siguiente.

| Tarea | Issue | Contenido |
|---|---|---|
| T0 | — | Mejoras al helper (sección 2) |
| T1 | #131 | Portabilidad y coherencia de metadatos |
| T2 | #132 | Primer asset ejecutable: agregador de jobs requeridos con test de paridad |
| T3 | #133 | Regla: paridad del agregador |
| T4 | #134 | Reglas: nombres de check requeridos solo desde eventos que evalúan el PR; verde rancio |
| T5 | #135 | Insumos de gates comparados contra la rama base; un gate dormido solo suprime hallazgos |
| T6 | #136 | Regla: test de comportamiento por control |
| T7 | #137 | Regla: exenciones por identidad |
| T8 | #138 | Paso y asset de readback del host |
| T9 | #139 | Sustituto de revisión con un solo mantenedor; salud del presupuesto |
| T10 | #141 | Regla: un gate requerido por PR es función del diff |
| T11 | #140 | Procedimiento de auditoría como asset |
| T12 | #143 | Graduar `ci-pattern` con dispensa |

Cada issue trae su evidencia `ruta:línea` ya verificada y el HR/sección que añade o modifica; la #144 sugiere la numeración HR-23 a HR-31. Hechos que el worker de la ola encontró y que afectan al trabajo:

- En la #131: el frontmatter dice `version: "0.1"` aunque el commit `b7b4c8b` publica «v0.2»; hay seis marcadores rotos `` ``MUST NOT` `` (líneas 76, 81, 94, 97, 98, 102); `references/incidents.md` lleva frontmatter de skill; la HR-8 de `ci-pattern` (la excepción de tamaño no depende de etiqueta) contradice el asset `check_pr_size.py` de `deterministic-quality-harness`, que exige la etiqueta. La elección de licencia (MIT aquí, Apache-2.0 en el espejo de APAP_WEB) es **decisión del usuario**.
- `deterministic-quality-harness` ya distribuye `check_pr_size.py` y `check_branch_name.py`; el asset de la #132 no debe duplicarlos.
- La HR-17 actual de `ci-pattern` prescribe el fallback `workflow_dispatch` que la #134 señala como agujero; esa issue la modifica.

**Sobre la graduación (T12), tres límites:**

- #118 (el propagador no filtra por consumer) y #128 bloquean la distribución dirigida: al graduar, la skill llega a todos los consumers habilitados (`dysflow`, `cadete`, `access2web-blueprint`, `APAP_WEB`, `Expedientes`), no solo a los `web`.
- El paso final de la graduación ejecuta `refresh-personal-symlinks.sh full` (el reconciliador). **No ejecutarlo** mientras el clon principal tenga el trabajo sin commitear de otra sesión sobre ese mismo script.
- `ci-pattern` tiene la descripción entre comillas; desde el PR #146 eso ya no rompe el validador.

**APAP_WEB:** las issues #1174–#1185 están aprobadas y sin empezar. El usuario no ha pedido implementarlas en esta sesión; su implementación de referencia alimenta los assets de la skill, así que conviene coordinar el orden con la ola de `team-skills`. Presupuesto de 400 líneas por PR, rama `<tipo>/<nº>-<slug>`, issue-spec obligatoria (ver `AGENTS.md` del repo).

## 4. Ciclo por tarea en `team-skills`

1. `git -C ~/personal-skills fetch origin` y worktree nuevo desde `origin/main` en `~/personal-skills-worktrees/<nombre>`, rama `<tipo>/<nº>-<slug>` (por ejemplo `fix/131-ci-pattern-portability`).
2. Delegar un escritor acotado con: la issue a leer desde el host, las superficies de edición exactas (`personal/ardelperal/ci-pattern/**` y, si la issue trae asset con tests, su suite y `.github/workflows/tests.yml`), test-first cuando haya test ejecutable, y los comandos de verificación.
3. Tras el retorno: releer la suite o el diff (spot check), y evaluar riesgo con `gentle-ai review assess --cwd <worktree> --agent claude-code --base-ref <base> --committed-only --json`. Si `review_due` es verdadero, ejecutar **literalmente** el `next_transition.command` devuelto, luego el START que devuelva, y transmitir el sobre de consentimiento al usuario sin resumirlo. Con `granted`: ejecutar la invocación devuelta, el STATUS que indique, lanzar en paralelo las capturas `review capture-result` con sus tokens exactos, y cerrar con el `acknowledge-approved` exacto. Los hallazgos consultivos no reabren la revisión: van como trabajo posterior.
4. `git push -u origin <rama>`; `gh pr create` con `Closes #N` y una etiqueta `type:*` (el repo no tiene plantilla de PR; cuerpo en inglés: What / Why / Change / Test evidence).
5. Esperar el CI una sola vez y de forma acotada (`timeout 420 gh pr checks <n> --watch`); recién creado el run puede devolver «no checks reported» y hay que repetir la llamada.
6. Con `mergeStateStatus: CLEAN`: `gh pr merge <n> --squash --match-head-commit <OID completo de 40 caracteres>`. Nunca `--delete-branch`.
7. Tildar la casilla en la #144, actualizar `odd/tasks/ci-pattern-portable-wave.md` y su espejo, y quitar el worktree local (`git worktree remove` + `git worktree prune`; la rama remota se conserva).

## 5. Gotchas

- **`team-skills` tiene `core.hooksPath=.githooks`.** Un commit en cualquier worktree ejecuta el reconciliador. `.git/hooks/post-commit` es un señuelo vacío. Commitear siempre con `git -c core.hooksPath=/dev/null commit …`. En esta sesión un commit lo disparó: abortó por un script ausente e hizo rollback, sin cambios en `~/.agents/skills/` ni en el manifest.
- **El clon principal `~/personal-skills` no se toca:** está en `b7b4c8b` (dos commits por detrás de `origin/main`) con una modificación sin commitear de otra sesión en `testing/suites/refresh-personal-symlinks/refresh-personal-symlinks.sh`. Trabajar siempre en worktrees desde `origin/main`.
- El historial de `main` en `team-skills` es lineal: squash.
- El job `unit` depende de `smoke`: con `smoke` rojo, `unit` se salta y las suites nuevas no corren.
- El validador de frontmatter solo recorre `skills/`; `personal/` no se valida en CI. Una suite o asset nuevo hay que añadirlo a la lista de `unit` en `.github/workflows/tests.yml`.
- El helper de graduación solo funciona ejecutado desde el repo; la copia propagada en `~/.agents/skills/` no resuelve la raíz.
- `gh pr view --json closingIssuesReferences` no existe en esta versión de `gh`; usar GraphQL.
- Comprobaciones habituales en `team-skills`: `bash testing/suites/frontmatter-validator/validate-frontmatter.sh skills`, `git ls-files -z '*.sh' | xargs -0 -n1 bash -n`, `bash testing/suites/i18n/test-scripts-castellano.sh`, y la suite que toque la tarea.

## 6. Dónde está cada cosa

| Qué | Dónde |
|---|---|
| Plan de la ola y casillas | `~/personal-skills/odd/tasks/ci-pattern-portable-wave.md` |
| Feature del gate de graduación (entregada) | `~/personal-skills/odd/tasks/graduation-waiver-gate.md` |
| Skill canónica | `personal/ardelperal/ci-pattern/` en `team-skills` |
| Espejo en el consumer | `skills/ci-pattern/` en APAP_WEB (se retira en la #143) |
| Seguimiento de la ola | `DysTelefonica/team-skills#144` |
| Épicas en APAP_WEB | #935 y #1129 |
| Memoria | Engram, proyecto `apap`: `audit/ci-issue-to-merge-2026-10-01`, `odd/ci-pattern-portable-wave/tasks`, `odd/graduation-waiver-gate/tasks` |

## 7. Decisiones abiertas para el usuario

1. Licencia de `ci-pattern` (MIT o Apache-2.0), al trabajar la #131.
2. En APAP_WEB, las decisiones de host que la #1175 deja al operador: crear las etiquetas `status:in-progress` y `status:blocked` o retirarlas de los docs, y deshabilitar squash y rebase.
3. Cuándo ejecutar el reconciliador tras la graduación, y si propagar a todos los consumers o esperar a la #118.
4. Si se implementa la ola de APAP_WEB y en qué orden respecto de la de `team-skills`.
