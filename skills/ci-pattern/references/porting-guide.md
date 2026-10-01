# Porting guide — checklist de pre-vuelo para adoptar el patrón de CI

Checklist por fases para adoptar el patrón de CI (gates deterministas,
presupuesto de revisión, evidencia por SHA, gobernanza de orquestación) en un
repositorio nuevo. Cada fase declara hard gates que deben pasar antes de iniciar
la siguiente. La regla que gobierna el checklist completo es una: la adopción no
se declara terminada antes de que un PR real recorra el ciclo completo (fase 5).

Este documento es el pre-vuelo. Los pasos de ejecución de la adopción (auditar,
medir, instalar, validar) viven en §4 de la `SKILL.md` de esta skill; los
parámetros por repo, en `assets/parameters.md`.

Cada gate cita el incidente real de la adopción en Cadete (2026-09-30/10-01)
que lo justifica. El post-mortem blameless completo del proceso de orquestación
vive en el repo `ardelperal/APAP_WEB`:
`docs/postmortems/2026-09-30-ci-pattern-adoption-cadete.md`. Las citas usan el
identificador «C-N» definido en ese documento.

## Fase 0 — Inventario (solo lectura)

Fase de lectura pura: ningún cambio de código, workflow ni gobernanza.

- **G0.1 — Stack y toolchain documentados.** Language, test runner, linters y
  disponibilidad del coverage driver, con versión. Previene C7: la baseline de
  cobertura se midió con la toolchain local (11503) mientras el runner de CI
  medía 11559 (xdebug sin pinear); el gate quedó rojo sobre main limpia.
- **G0.2 — Inventario de gobernanza.** Protecciones de rama, rulesets,
  CODEOWNERS, plantillas de issue/PR y workflows de validación existentes, con
  la lista de eliminación confirmada por el operador. Previene C3: las
  prescripciones rotas (formato abreviado de issue, nombre de rama ilegal)
  aparecieron donde la gobernanza de destino no estaba instalada ni verificada.
- **G0.3 — Ramas y roles.** Qué rama es la base activa, qué ramas son de
  release o de integración y quién puede empujar a cada una.
- **G0.4 — Mecanismo de deploy.** Quién despliega producción y cómo: ¿el push a
  la rama base dispara el deploy o hay herramienta externa? Si no existe
  mecanismo de deploy, el binding evidencia↔deploy de la fase 4 no se instala.
- **G0.5 — Inventario de runners.** GitHub-hosted frente a self-hosted, y qué
  job corre en cada uno. Previene C2: el job de security corría en
  GitHub-hosted, no en la flota self-hosted; el diagnóstico «Docker daemon» ×3
  salió de grepear logs del runner equivocado en lugar de pedir la evidencia
  por paso con `gh api jobs/<id>`.
- **G0.6 — Estado de release.** Qué está sin liberar en el repo. Nunca adoptar
  a mitad de un fix sin liberar: el ruido del cambio de gobernanza se mezcla
  con el fix pendiente y ambos quedan sin dueño claro.
- **G0.7 — Clones locales frente a workspaces de CI.** Identifique los
  workspaces de CI del repo y declárelos fuera de límites para cualquier
  edición. Previene C5: los workspaces de CI pertenecen al runner; editar en
  ellos compite con el runner sobre el mismo working tree.

Gate de salida de fase: los siete puntos inventariados por escrito y la lista
de eliminación de gobernanza confirmada por el operador.

## Fase 1 — Verificación de realidad de la propagación

- **G1.1 — El mecanismo de propagación de skills funciona, verificado en
  vivo.** Audit el mecanismo real del destino: hooks activos, scope del
  reconciliador, overlays y markers. Ejecute o inspeccione el mecanismo; no se
  fíe de la documentación ni de la memoria de una sesión previa. Previene C4:
  la premisa de propagación era falsa (el hook post-commit era un no-op
  retirado y el reconciliador solo leía `skills/`), y se descubrió auditando
  después de haberla usado; los espejos quedaron stale durante el tramo.

Gate de salida de fase: una ejecución real del mecanismo que deja el artefacto
esperado en el destino, con la evidencia de esa ejecución.

## Fase 2 — Aislamiento del entorno

- **G2.1 — Clone de desarrollo fresco.** Todo el trabajo de adopción ocurre en
  un clone de desarrollo fresco, nunca en un workspace de CI. Previene C5.
- **G2.2 — Un worktree por actor concurrente.** Antes de tocar nada, declare
  cuántos actores van a trabajar en paralelo y asígneles un worktree cada uno.
  Previene C5: dos workers colisionaron en el working tree compartido de
  `apap-app` y uno commiteó sobre la rama del otro en pleno vuelo (HR-24).
- **G2.3 — Chequeo de envenenamiento por `.env`.** Compruebe si un `.env` en la
  raíz del repo filtra variables al entorno de tests; aísle la suite o
  documéntelo como premisa del entorno. Previene C6: el `.env` gitignored de la
  raíz filtró `APAP_*` a pydantic Settings y produjo 5 rojos ambientales que
  solo existían en la máquina de desarrollo (HR-28).
- **G2.4 — Toolchain pineada para toda baseline medida.** Toda cifra que un
  gate compare (cobertura, conteos, huellas) se mide con la misma toolchain que
  usará el runner de CI, pineada. Previene C7 (HR-26).
- **G2.5 — Baterías contra la revisión desplegada.** Toda batería contra un
  deploy corre desde un worktree en el SHA desplegado, nunca con los tests de
  la rama por defecto. Previene C1: la batería se lanzó con los tests de main
  contra la revisión desplegada y produjo 18 falsos fallos; el worktree en la
  revisión correcta tuvo que prepararlo la IA de otra sesión.

Gate de salida de fase: cada actor con su worktree, la suite verde sin el
`.env` local y la toolchain de medición pineada y documentada.

## Fase 3 — Reemplazo de gobernanza

- **G3.1 — Reemplazo sin hueco.** La gobernanza vieja se retira y la nueva se
  instala en el mismo PR: nunca un PR que solo retira y otro posterior que
  instala, porque el hueco entre ambos es una ventana sin gates.
- **G3.2 — Plantillas canónicas.** Issue y PR con las secciones exactas que los
  gates leen y con el contrato de revisión visible (presupuesto, excepción como
  campo de datos, cadena de PRs).
- **G3.3 — Aprobador nombrado.** El operador que aprueba issues y revisa PRs
  queda nombrado en la gobernanza instalada; un pipeline sin aprobador named
  detiene cada issue en la puerta.

Previene C3 en los tres gates: el formato abreviado de issue costó reruns, el
nombre de rama ilegal violó el validador del destino y las superficies con
prosa entre paréntesis fueron rechazadas por el contrato del worker.

Gate de salida de fase: un PR de gobernanza mergeado que instala plantillas,
validadores y protección de rama juntos, sin ventana sin gates.

## Fase 4 — Contratos cableados

- **G4.1 — Issue-spec equivalente** instalado y validando el formato canónico
  de issue en el destino.
- **G4.2 — Presupuesto de tamaño** con excepción declarada como campo de datos
  (`size-exception-reason:`) y cadena de PRs para lo que no cabe.
- **G4.3 — Preflight ejecutable** en local con un solo comando, paridad con el
  job de lint (HR-4).
- **G4.4 — CI en la rama base**, net-new si el destino no tenía.
- **G4.5 — Binding evidencia↔deploy solo si existe deploy.** El estado de
  commit por SHA (HR-10) se instala únicamente cuando la fase 0 inventarió un
  mecanismo de deploy; sin deploy no hay evidencia que registrar y el gate solo
  añade ruido.

Previene C3 en G4.1-G4.3: la receta de trabajo mencionaba una ruta de tests
inexistente (`tests/test_required_jobs.py`) y el repo equivocado para la wave
de #1160 (dijo cadete, los ficheros eran de APAP_WEB). Verifique en vivo cada
ruta, rama y repo que una prescripción mencione antes de delegar (HR-25).

Gate de salida de fase: cada contrato ejecuta al menos una vez contra datos
reales del destino (una issue canónica valida, un PR de prueba mide, el
preflight corre completo en local).

## Fase 5 — Primer PR real como test de aceptación

- **G5.1 — El primer PR real recorre el ciclo completo.** Issue canónica,
  worktree dedicado, preflight completo, PR con etiquetas en el comando de
  creación, CI verde, merge. La adopción no se declara terminada antes de ese
  PR; ningún ensayo con PRs de prueba lo sustituye.
- **G5.2 — El patrón completo viaja en la skill antes de la adopción.** Todo
  sub-patrón que el destino necesite (gates dormibles incluidos) debe estar en
  la skill antes de empezar. Previene C8: el patrón dormible (R15) no estaba en
  la skill cuando Cadete lo necesitó y llegó a mitad de vuelo desde el benchmark
  de gentle-ai.

Gate de salida de fase: el primer PR real mergeado bajo el pipeline nuevo y el
veredicto de ese ciclo registrado como evidencia de la adopción.

## Trazabilidad fase → incidente

| Fase | Incidente que la fase cierra |
|---|---|
| 0 | C1 (batería desfasada), C2 (runner equivocado), C7 (toolchain sin pinear) |
| 1 | C4 (premisa de propagación falsa) |
| 2 | C1 (worktree de revisión), C5 (colisión de workers), C6 (.env), C7 (baseline) |
| 3 | C3 (prescripciones rotas de gobernanza) |
| 4 | C3 (rutas y repos no verificados) |
| 5 | C8 (patrón dormible ausente) y la cadena completa como test de aceptación |
