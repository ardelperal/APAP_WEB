# Post-mortem — adopción del patrón de CI en Cadete (2026-09-30/10-01)

Post-mortem blameless del proceso de orquestación de la adopción del patrón de
CI en `DysTelefonica/cadete`. El alcance es el proceso de orquestación (la
sesión de IA y sus handoffs); el código de aplicación de Cadete y su post-mortem
de aplicación son territorio del operador y quedan fuera de este documento.

Causas de sistema, nunca de personas (HR-21). Los identificadores «C-N» de este
documento son los que cita la guía de porting
(`skills/ci-pattern/references/porting-guide.md`).

## Timeline (UTC)

No hay marcas horarias exactas registradas; la secuencia es la del registro de
fricciones de la épica #935.

1. 2026-09-30 — **C1.** Batería lanzada con los tests de main contra la
   revisión desplegada: 18 fallos falsos. El worktree en la revisión correcta
   tuvo que prepararlo la IA de otra sesión.
2. 2026-09-30 — **C2.** Diagnóstico «Docker daemon» ×3 y issue de infra falsa
   `DysTelefonica/cadete#1130` (cerrada corregida). La evidencia correcta
   estaba en la API por paso (`gh api jobs/<id>`); el job de security corría en
   GitHub-hosted, no en la flota self-hosted.
3. 2026-10-01 — **C3.** Prescripciones rotas del orquestador: repo equivocado
   para la wave de #1160 (dijo cadete, los ficheros eran de APAP_WEB), ruta de
   tests inexistente (`tests/test_required_jobs.py`), nombre de rama ilegal
   (`docs/ci-pattern-mirror` frente a `<tipo>/<N>-<slug>`), formato abreviado
   de issue (costó reruns) y superficies con prosa entre paréntesis rechazadas
   por el contrato del worker.
4. 2026-10-01 — **C4.** Premisa de propagación falsa: se asumió que el hook
   post-commit propagaba las skills personales; el hook era un no-op retirado y
   el reconciliador solo lee `skills/`. Se descubrió auditando después de
   usarla; los espejos quedaron stale durante el tramo.
5. 2026-10-01 — **C5.** Dos workers concurrentes colisionaron en el working
   tree compartido de `apap-app`: uno commiteó sobre la rama del otro en pleno
   vuelo.
6. 2026-10-01 — **C6.** El `.env` gitignored de la raíz del repo filtró
   `APAP_*` a pydantic Settings: 5 rojos ambientales de tests que solo
   existían en la máquina de desarrollo.
7. 2026-10-01 — **C7.** Baseline de cobertura medida con la toolchain local
   (11503) distinta de la del runner de CI (11559, xdebug sin pinear): gate
   rojo sobre main limpia. Corregido midiendo con la toolchain del propio
   runner (`--update-baseline`).
8. 2026-10-01 — **C8.** El patrón dormible (R15) no estaba en la skill cuando
   Cadete lo necesitó; llegó a mitad de vuelo desde el benchmark de gentle-ai.

## Impact

- Ciclos de CI quemados: la batería con 18 falsos fallos y los reruns por las
  prescripciones rotas.
- Una issue de infra falsa (`DysTelefonica/cadete#1130`), abierta y cerrada
  corregida.
- Espejos de skill stale durante parte del tramo (propagación no operativa).
- Colisión de trabajo concurrente resuelta sin pérdida, con coste de
  reordenación de ramas.

## Root cause

Tres causas de sistema, sin las cuales ninguno de los ocho incidentes ocurre:

1. **La adopción se puso en marcha antes de que existiera la guía de porting.**
   Las prescripciones salieron de la memoria del orquestador, no de
   verificación en vivo contra el destino.
2. **La premisa del mecanismo de propagación no se auditó antes de depender de
   ella.** La documentación del mecanismo se tomó como evidencia del
   funcionamiento.
3. **No existía contrato de aislamiento.** Ni entre actores concurrentes (un
   solo working tree compartido) ni frente al entorno local (`.env` y toolchain
   sin pinear entraron en las mediciones y los tests).

## What worked

- Los gates de los propios workers cazaron la mayoría de los errores de
  prescripción antes de que aterrizaran: superficies con prosa rechazadas y
  formato de issue corregido a costa de reruns, no de merges malos.
- Cero merges malos a main y cero ficheros de la aplicación de Cadete tocados
  por la orquestación.
- El veredicto de la batería fue honesto: los 18 fallos se clasificaron como
  desfase de revisión (tests de main contra un deploy anterior), no como fallo
  del deploy, y el worktree en la revisión desplegada cerró la brecha.

## What failed

Los ocho incidentes C1-C8 del timeline, todos de orquestación:

- Batería desfasada por falta de worktree en la revisión desplegada (C1).
- Diagnóstico de infraestructura por log-grep en el runner equivocado, con
  issue falsa incluida (C2).
- Prescripciones del orquestador emitidas sin verificación en vivo: repo,
  rutas, ramas y formato canónico (C3).
- Premisa de mecanismo (propagación) creída sin auditoría (C4).
- Working tree compartido entre actores concurrentes (C5).
- Suite de tests permeable al `.env` local (C6).
- Baseline medida con toolchain distinta de la del runner (C7).
- Skill incompleta en el momento del vuelo: el sub-patrón dormible faltaba (C8).

## Action items (como issues)

Cada action item se abre como issue de GitHub con owner (HR-21); este
documento no los sustituye.

1. **Porting guide de pre-vuelo** — este entregable: la guía por fases en
   `skills/ci-pattern/references/porting-guide.md`, espejada desde
   `personal-skills` (Refs #1169, #1170, #1187). Cierra C1-C8 por diseño.
2. **Auditar el mecanismo de propagación antes de usarlo** (hook activo, scope
   del reconciliador, overlays): una ejecución real con artefacto verificado
   como gate de entrada. Cierra C4.
3. **Un worktree por actor concurrente**, aplicado a la propia orquestación y
   no solo a los workers (HR-24). Cierra C5.
4. **Aislar la suite de pytest del `.env` local** y documentarlo como premisa
   del entorno (HR-28). Cierra C6.
5. **Pinear la toolchain de toda medición que un gate compare** con la que usa
   el runner (HR-26). Cierra C7.
6. **Verificar en vivo toda prescripción antes de delegar**: rutas, ramas,
   repos y formato canónico contra el destino real (HR-25). Cierra C3.
7. **Registrar la corrección de `DysTelefonica/cadete#1130`** como evidencia en
   el catálogo de fricciones de Cadete, para que el diagnóstico por API por
   paso quede como regla y no como anécdota. Cierra C2.
8. **Completar la skill antes del próximo vuelo**: auditar que todo sub-patrón
   que el destino necesite (gates dormibles, HR-18) está en la skill antes de
   empezar la adopción. Cierra C8. La batería contra la revisión desplegada
   (C1) queda cubierta por el anti-pattern existente en la skill y por G2.5 de
   la guía.
