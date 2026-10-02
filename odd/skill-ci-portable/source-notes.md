# Notas fuente para la skill «ci-pattern» (CI portable, trabajo de dos ramas en paralelo)

Estado: material de trabajo, NO es la skill. La skill se escribe al final, cuando el CI cumpla la definición de «hecho» de la sección 9. Origen: sesión de 2026-09-29/30 sobre `ardelperal/APAP_WEB`. Lo verificado lleva evidencia (PR, run, comando); lo no verificado está marcado **[no verificado]**.

## 1. Premisas del patrón

1. Dos ramas en paralelo sobre el mismo repositorio, cada una en su worktree y con superficies que no se solapan (personas o agentes distintos).
2. Política de revisión: presupuesto de 400 líneas por PR (`additions + deletions`), troceado en PR encadenados, `size:exception` como último recurso.
3. Rama por defecto protegida: 3 checks requeridos (`branch-name`, `required`, `pr-size / pr-size`), `strict: true`, `enforce_admins`, sin force-push. Fusión con commit de fusión (`--no-ff`), **la rama remota se conserva**.
4. Entrega a producción por deploy automático en cada push a la rama por defecto, con evidencia por revisión.

## 2. Reglas de diseño (con la evidencia que las motivó)

| # | Regla | Evidencia |
|---|---|---|
| R1 | Si la política pide partir el trabajo, ningún gate puede penalizar partir | #956, #933, #941/#896, #1121 (comentario en #935) |
| R2 | Un gate lee datos estructurados (rama, etiquetas, campos de API), no prosa | #956: enlace desde la rama y `closingIssuesReferences`; #1121: campo del cuerpo |
| R3 | Todo gate nuevo que toque producción se ejecuta de verdad antes de darlo por terminado | #1134: el smoke recibía 403 de Cloudflare por el `User-Agent` de `urllib`; solo lo cazó una ejecución real |
| R4 | Un gate nunca dice «OK» sin haber medido | vulture: `OK (0 confirmed-dead)` sin vulture instalado y una nota que sugería bajar la BASELINE (#1142) |
| R5 | Todo lo que el CI ejecuta debe poder ejecutarse en local con un solo comando (paridad de preflight) | tres PR llegaron a CI con un fallo que la suite local no veía: UTF-8 en #1082, `check_alantyle` en #1133, y el del guard de vulture (#1119) |
| R6 | La evidencia va ligada a una revisión (SHA), nunca a una variable global | #1082: la variable global bloqueaba todo o aprobaba para siempre |
| R7 | Un gate nuevo lleva su arranque automático o una degradación explícita para revisiones anteriores a su existencia | arranque de `release-e2e-gate`: hubo que ejecutar el smoke real sobre la revisión desplegada |
| R8 | Los datos de un PR controlados por el autor no viajan por `$GITHUB_OUTPUT` con delimitador fijo | adopción en #1141: inyección de salidas con una línea `EOF` |
| R9 | Los registros acumulativos de varias sesiones no se guardan con clave de tema (upsert sustituye) | Engram #4368 perdió 10 de 11 entradas; recuperado de `sync_mutations` (#4369-#4371) |
| R10 | Los mensajes de un gate dicen la causa real | `issue-spec`: «missing or empty section» cuando el problema era el nivel de encabezado |
| R11 | La revisión y el CI validan el árbol final, no un subconjunto | #1082: `-k "workflow or release"` no cazó el test de convención de UTF-8 |
| R12 | Un job de Actions se detiene en el primer paso fallido: hay que reproducir **todos** los pasos posteriores antes de empujar | #1133: tras corregir `check_alantyle`, ejecuté los otros 16 pasos de `lint` |
| R14 | **Auto-auditoría y destilación de fricciones**: el sistema de CI debe incluir su propio protocolo de mejora continua. Toda fricción se registra con evidencia, se arregla por el pipeline, se destila en regla, y la recurrencia dispara automatización. La skill debe llevar esta sección como sección propia (no como consejo), porque un CI sin mecanismo de destilación acumula deuda invisible | Protocolo de mejora continua de `ci-playbook.md` (regla → rojo que la creó → procedimiento correcto); épica #935 (2026-09-29/30): 20+ fricciones registradas en #4368/#935, arregladas por el pipeline y destiladas en las 20 reglas del playbook |
| R15 | **Gates dormidos, no retirados**: un gate que pierde su justificación (sin defecto real cazado, rechazado por el operador) NO se elimina: se duerme tras un policy file (`enforcement: "dormant"`) con el motor construido y probado, y la re-activación es un cambio de datos que pasa por review (patrón `grandfather-size-exceptions.json` de Gentleman-Programming/gentle-ai; evidencia: `check_alantyle` informativo #1151 y `check_crap`/`check_mutation_sites` dormidos en la era #1167) | Informe gentle-ai IDEA T1 + PR #1167 |
| R16 | **Orquestación determinista (jerarquía mecanismo > script > IA)**: nada espera a una IA. El auto-merge armado espera CI, `allow_update_branch` actualiza ramas, los required checks bloquean, los scheduled workflows recuerdan; donde no hay mecanismo, un script versionado con deadline y fallback; la IA solo para juicios (disposiciones, conflictos de contenido, gobierno). Un watcher vivo de sesión es un actor no determinista | Épica #935 (2026-09-29/30): vigía zombi de otra sesión con autoridad de merge, contadores congelados entre polls, bucles `--watch`; playbook `ci-playbook.md` regla 20 |
| R17 | **Un worktree por actor concurrente**: dos workers en el mismo working tree colisionan; toda tarea delegada concurrente usa worktree y rama propios, y el trabajo abandonado se reclama desde el estado real (git, PR, issue), no desde la memoria de la sesión | Colisión de shared-checkout del 2026-10-01: un worker commiteó sobre la rama del otro a mitad de vuelo |
| R18 | **Las prescripciones del orquestador son hipótesis**: SHA, conteos de pasos, rutas de tests y superficies editables se verifican en vivo antes de ejecutar, y el trabajo existente se reutiliza en lugar de duplicarse | Vivido 4× en el tramo final de la épica: preflight con 19 vs 20 pasos, §15.8 inexistente, SHA de slice-2 distinto, ruta de tests inexistente |
| R19 | **Toolchains pineadas para mediciones**: todo gate que compara números (cobertura, baselines) mide con la misma toolchain versionada que lo juzga en CI, o se re-mide con la toolchain del juez | Baseline local 11503 vs runner 11559 por xdebug sin pinear: conteos de líneas no comparables entre toolchains |

## 3. Arquitectura del pipeline (tal como quedó)

```
PR:   branch-name | pr-size (campo del cuerpo) | issue-spec (rama+etiquetas+closingIssuesReferences)
      lint (16 pasos) | typecheck | test (cobertura 85%) | integration (Postgres real) | e2e (solo si cambia UI)
      security (pip-audit, gitleaks, trivy config) | CodeQL (no requerido) | build
      required  <- agregador que falla cerrado (script con matriz de skips esperados)

main: deploy.yml
      evidence (CI verde del head del PR) -> release-e2e-gate (verdicto de la revisión ANTERIOR:
      release/smoke-production + release/e2e-production) + ui-e2e-gate
      -> deploy (build, Trivy, Cosign keyless, promoción por digest, webhook, verificación de revisión, rollback)
      -> production-smoke (sin secretos ni autenticación; escribe release/smoke-production)
      -> release-e2e-record (selector de rutas sensibles: pending o success "not-required")
```

Estados por revisión (commit statuses): `release/smoke-production` (automático), `release/e2e-production` (manual solo si el rango toca rutas sensibles; bypass `skipped:<motivo>` por SHA).

## 4. Piezas reutilizables (candidatas a `assets/` de la skill)

| Pieza | Función | Estado |
|---|---|---|
| `scripts/check_release_evidence.py` | evaluador fail-closed de un contexto de estado por SHA (`--context` con lista cerrada) | en `main` |
| `scripts/check_release_e2e_required.py` + `.github/release-e2e-paths.txt` | decide si el rango toca rutas sensibles; falla cerrado | en `main` |
| `scripts/production_smoke.py` | smoke sin autenticación con `User-Agent` propio, reintentos, host de la redirección | en `main` (#1135) |
| `scripts/check_pr_size.py` + `pr-size.yml` | presupuesto con excepción declarada en el cuerpo | en `main` (#1141) |
| `scripts/check_issue_specs.py` | trazabilidad determinista: rama, etiqueta `chain:partial`, `closingIssuesReferences` | en `main` (#1111) |
| `scripts/check_required_jobs.py` | agregador que falla cerrado con matriz de skips esperados | ya existía |
| `scripts/preflight.py` | reproduce en local los pasos `run:` del job `lint` leyendo `ci.yml` (sin lista que derive) | en `main` (#1145) |
| plantilla de PR y de issues | campos que los gates leen | en `main` |

Parámetros a extraer para que sea portable: regex de rama, presupuesto de líneas, nombres de etiquetas (`chain:partial`, `size:exception`), contextos de estado, lista de rutas sensibles, URL de salud, `User-Agent`, host de producción, versión de Python, política de merge.

## 5. Catálogo de fricciones (21) y estado

Fuente única: comentarios de #935 (consolidación del 2026-09-30). Resumen: **resueltas** A1, A6, A8, A9 (falso verde de vulture, #1142/#1143), B1, B5, B9; **abiertas** A2, A3, A4, A5, A7, A10, A11, B2 (`strict` sin cola: invalida PR abiertos; observado tres veces), B3 (#1119), B4, B7, B8, B10; **vigilar** B6. Hallazgo adicional sin issue: `actionlint` detecta `services.minio.command`, clave inexistente en Actions (`ci.yml:1251`).

R15 nace del benchmark gentle-ai (patrón dormant policy) y aplica la corrección de la épica #935: informativo sin policy file pierde el candado construido; dormant lo conserva.

**Hallazgo posterior (B11, 2026-09-30):** `issue-spec` depende de `closingIssuesReferences` y GitHub puede no registrar un cierre correcto sin causa visible (`willCloseTarget: false`, también en un PR nuevo); ningún gesto del autor lo arregla. Regla candidata R13: un gate que depende de un dato que el autor no puede corregir debe dar un mensaje que diga que el fallo es de la plataforma y ofrecer una vía manual auditable. B12: fallo transitorio del runner en el paso de Python de `issue-spec`; B13: nombre de paso truncado por un `#` sin comillas en `ci.yml`.

## 6. Veredicto de gates (auditoría inicial, **[no verificado]** salvo lo señalado)

- **Mantener:** `required`, `pr-size`, `branch-name`, `integration` (Postgres real), `security`, CI de PR, `ruff`/`mypy`.
- **Reforzar:** cobertura (solo unit con dobles; 85% sobre `app` y `migration`), e2e de PR (6 tests, ninguno envía formularios), `mutation`/`security-deep` (solo en tag/cron: HR-22).
- **Simplificar o quitar (sin evidencia de defecto real):** `check_mutation_sites` (BASELINE 464 y subiendo), `check_crap` y docstrings (informativos), `check_alantyle` (bloqueante de estilo de docs; falló por una palabra en mayúsculas), `test_ci_workflow.py` (fichero más editado del repo).
- **Falta:** `actionlint` en el `lint` (hoy cazó `services.minio.command`, clave inexistente en Actions), y un job de preflight que reproduzca los 16 pasos.

## 7. Reglas para trabajar en paralelo (dos ramas)

1. Un worktree por rama; superficies disjuntas; ficheros que toca todo PR (`AGENTS.md`, índices de docs, BASELINE, `.atl/skill-registry.md`, `test_ci_workflow.py`) asignados a un único PR a la vez.
2. Reclamar la issue con un comentario y una rama con el número; una reserva sin rama ni PR tras un día está caducada.
3. `strict` obliga a actualizar la rama tras cada merge ajeno: presupuestar ~15 min de CI repetida; con cola de fusión desaparece.
4. Etiquetar al crear el PR (`gh pr create --label`), no después: etiquetar después no relanza `issue-spec`.
5. Trabajo abandonado de otro agente: comprobar procesos vivos, adoptar con un commit propio, revisar (no confiar) y corregir en otro commit.
6. Límite de uso y pausas: los estados de merge cambian; volver a leer `origin/main` y la base de cada revisión antes de continuar.

## 8. Lecciones operativas (verificadas)

- Cloudflare responde 403 al `User-Agent` por defecto de `urllib`; `curl` y un agente propio pasan.
- `closingIssuesReferences` se rellena unos segundos después de crear el PR.
- `gh pr merge` falla con «3 of 3 required status checks are expected» cuando la rama está obsoleta.
- La revisión nativa: usar el comando de STATUS que devuelve el START (con su `base-ref` fijado a un SHA), no reconstruirlo con `origin/main`; el documento de tareas sin seguimiento fuerza una selección de ficheros (apartarlo durante la revisión).
- `pgrep -f "<texto>"` coincide con el propio comando de shell; comprobar procesos con `ss`/`ps`.
- Homebrew de este equipo pertenece a otro usuario: los binarios oficiales van a `~/.local/bin`.

## 9. Definición de «hecho» para el CI (criterio para escribir la skill)

1. Sin falsos verdes conocidos (A9 cerrado; ningún gate imprime OK sin medir).
2. Paridad de preflight: un comando reproduce los pasos de `lint` y `actionlint` (#1119 **hecho**: `scripts/preflight.py`, 19 pasos en ~30 s; falta `actionlint` como paso).
3. `strict` resuelto (cola de fusión o alternativa medida) o su coste declarado y aceptado.
4. Una cadena real de PR encadenados con `chain:partial` y `Part of`-libre pasada de extremo a extremo con CI en cada tramo.
5. Gates sin evidencia de defecto real, simplificados o retirados con una medición.
6. Deploy con evidencia automática por revisión, sin trámites manuales salvo rutas sensibles.
7. Documentación alineada con los workflows (ninguna contradicción abierta).

## 10. Esquema propuesto de la skill (según `skill-style-guide`)

Nombre `ci-pattern`. Secciones canónicas: contrato de activación; reglas duras (R1-R12); puertas de decisión (¿repo con dos ramas en paralelo?, ¿hay producción?, ¿hay runners propios?); pasos de ejecución (auditar → medir → instalar el patrón → validar en real); contrato de salida; antipatrones en tabla síntoma/arreglo (los de la sección 5); `assets/` con los scripts y plantillas de la sección 4 parametrizados; `references/` con este catálogo y el veredicto de gates. Presupuesto de cuerpo: respetar el de la guía de estilo (cifras en su `SKILL.md`).

## 11. Pendiente de recoger antes de escribir la skill

- Resultado de #1142 (guard de vulture), de #1119 (paridad de preflight) y de #1118 y #1120 (otra ola).
- Decisión sobre `strict`/cola de fusión (#958) y sobre `check_alantyle`.
- Cifras medidas de coste por PR tras los cambios.
- Cadena real de PR encadenados con CI en cada tramo.
