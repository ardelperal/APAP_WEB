# Tarea: compilar el CI playbook portátil (`odd/skill-ci-portable/ci-playbook.md`)

Fecha: 2026-10-01. Estado: completado (untracked, sin tocar ficheros trackeados).

## Qué se hizo

Playbook canónico de CI para agentes IA en `ardelperal/APAP_WEB`: 17 reglas con la forma **Regla → Por qué costó un rojo → Procedimiento correcto**, agrupadas por ciclo de vida (CREAR ISSUE → ABRIR PR → CI EN VUELTA → CLASIFICAR ROJOS → MERGE → PRODUCCIÓN → ENTORNO Y RECURSOS), en castellano formal (usted).

Fuentes minadas: `odd/HANDOFF-ci-2026-09-30.md` (§6, 8 lecciones), comentarios de la issue #935 («Consolidación de fricciones del CI», A1-A11/B1-B10, y «Nuevo hallazgo B11») recuperados por API, y las 15 fricciones de sesión provistas por el orquestador como verificadas.

## Verificación contra origin/main (`0c78ac9`) y la API en vivo

| Claim | Resultado |
|---|---|
| Preflight 20/20 pasos incl. actionlint | **No verificado tal cual**: `uv run python scripts/preflight.py --list` sobre `52fd1c5` lista **19 pasos** y `actionlint` no aparece en el job `lint` de `ci.yml` (ni local ni origin/main, grep sin coincidencias). El 20.º paso corresponde a la decisión 4 del handoff (§3.4), aún pendiente. El playbook dice 19 con nota. |
| merge-workflow.md §15.8 | **No existe** en origin/main: el §15 termina en §15.7 y no hay ninguna mención de `update-branch` ni auto-merge en el fichero. El playbook cita el procedimiento como verificado por API (settings) y señala el rezago del doc. |
| Settings: `allow_auto_merge`/`allow_update_branch` | **Verificado en vivo**: `{"allow_auto_merge":true,"allow_update_branch":true}`; protección de `main`: `strict:true`, contexts `branch-name`, `required`, `pr-size / pr-size`. |
| #935 comentarios | **Recuperados íntegros** (ids 5904060639 y 5913515417): B11 documentado con GraphQL `willCloseTarget: false`, y la consolidación A1-A11/B1-B10 tal como las cita el playbook. |
| Fricciones de sesión 1-15 | Tomadas como verificadas por provisión del orquestador (no contrastadas una a una contra PRs remotos, salvo las del cuadro anterior). |

## Desviaciones honestas respecto al encargo

1. «20/20 pasos incl. actionlint» se corrigió a «19 verificados; 20 cuando entre actionlint (decisión 4 del handoff, pendiente)».
2. La regla 11 no atribuye la documentación a §15.8 (inexistente); cita la evidencia de settings en vivo y nota el rezago doc (P3: gana el código).
