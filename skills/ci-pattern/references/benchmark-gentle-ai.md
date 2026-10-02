# Benchmark: ingeniería inversa del CI de Gentleman-Programming/gentle-ai

Resumen del informe de investigación (2026-09-30, HEAD de gentle-ai =
`717087b`, clon shallow, consultas read-only de metadatos públicos). El
informe completo fue fuente de trabajo de la destilación y no se versiona en
el catálogo; este doc conserva las ideas con su evidencia.

## Ideas transferibles (T1-T9)

| Idea | Qué hace gentle-ai | Estado en este patrón |
|---|---|---|
| T1 — Doble gate de tamaño, uno dormido | Check informativo para el autor + política `pull_request_target` dormida tras `grandfather-size-exceptions.json` con transición validada | Adoptado como R15/HR-18: el policy file de gates dormibles (`assets/parameters.md`) |
| T2 — Ratchet sobre baseline, no clean gate | `comm -13 baseline current` con `--update` y locale pineado | Adoptado (HR-15); forma para `check_mutation_sites` y vulture |
| T3 — Drift guard con `test -list` antes de todo manifest | Un selector que no matchea nada es un agujero silencioso | Adoptado para el propio workflow (actionlint, nombres de paso) |
| T4 — Preflight de release como scripts versionados reusables | `require-ci-success.sh`, `release-preflight.sh`, verificación de lo publicado | Parcialmente adoptado (preflight canónico); leer de vuelta lo publicado sigue abierto |
| T5 — No-gate documentada | La suite separada documenta en su comentario por qué no bloquea y cuándo vuelve | Adoptable: toda decisión de no bloquear queda visible y fechada |
| T6 — Sharding de suite por coste medido | Shards balanceados por segundos medidos, no por alfabeto | Pendiente (ardelperal/APAP_WEB#939); método recomendado |
| T7 — `workflow_dispatch` para rerun tras cambio de workflow | Documenta que `rerun` rechaza runs con el workflow cambiado | Adoptado (HR-17, fallback del §3) |
| T8 — Contrato versionado + bundle firmado | `CONTRACT_SEMVER` en repo, asset firmado aparte | No aplica aún: sin API pública |
| T9 — Documento por tarea con secciones fijas | Cada tarea produce un doc: Claimed, Root-cause, Tasks, Evidence | Adoptado: el formato de documento por tarea con secciones fijas |

## Patrones de colaboración humano-IA (COL1-COL5)

| Patrón | Idea | Estado |
|---|---|---|
| COL1 | Cada operación pide su autorización explícita; la skill no sondea credenciales | Principio adoptado |
| COL2 | Recibo por issue (no por épica) con timeline de runs | Adoptado en el formato de documento por tarea con secciones fijas |
| COL3 | Sin atribución de IA como política declarada, aplicada por revisión humana | Adoptado (HR-14) |
| COL4 | Un solo parse reusado por consumidores posteriores en el mismo workflow | Adoptable; evita re-escanear datos ya validados |
| COL5 | Doble enforcement: regla en el ruleset + explicación en la skill | Adoptado: gates + skills versionadas |

## Rechazados (NC1-NC6) y por qué

| Rechazo | Motivo |
|---|---|
| NC1 — Tres sistemas operativos en cada push | Sin binarios nativos; runners macOS/Windows 10x más caros |
| NC2 — `pull_request_target` para política trusted | Ejecuta con secretos; cada paso añadido exige auditoría. Solo con caso claro |
| NC3 — Complejo de release firmado (Minisign, environments) | Inversión para binario distribuido; aquí el deploy es Coolify con Cosign |
| NC4 — Policies dinámicas de environment | Innecesario en single-branch pre-MVP |
| NC5 — Notificaciones a Discord | Informativo sin comunidad que lo exija |
| NC6 — Conventional Commits como regla dura de ruleset | El repo lo aplica a PRs; extenderlo a commits queda como decisión del operador |

## Claims verificados y no verificados

Verificados con evidencia (fecha de corte 2026-09-30): topología de workflows,
ruleset único con seis reglas, `enforcement: "dormant"` en el policy file,
diez ejecuciones consecutivas en fallo de la suite Windows separada, el
comentario histórico de `require-ci-success.sh` (v2.2.0 publicó verde con CI
rojo en `ee83e83d`).

No verificados: frecuencia exacta de fallo del CI principal (muestra sesgada),
si `darwin-runtime` está en los required checks, el uso real de
`recovery_state=verify-existing` en producción y la cobertura individual de
cada journey de bench. El informe conserva la lista completa y sus matices.

## Aprendizajes clave para este patrón

1. Cada release exige leer de vuelta lo publicado; ningún gate se fía del verde
   previo sin comprobarlo contra el SHA exacto.
2. Cada manifest curado exige drift guard antes de ejecutar.
3. Cada política dormida vive en el repo lista para activarse: el gate se
   construye y se prueba cuando la decisión está fría, se activa cuando la
   decisión está tomada.
4. La honestidad de un gate es declarar lo que no caza; esa declaración reduce
   la deuda oculta y hace reversible la activación.
