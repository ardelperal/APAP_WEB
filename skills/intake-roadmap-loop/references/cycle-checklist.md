# Checklists por compuerta

Cuatro checklists que la skill `intake-roadmap-loop` aplica en cada gate. Marque cada ítem antes de avanzar a la siguiente compuerta. Un ítem sin marcar bloquea el avance.

## 0 — Intake

- [ ] La fuente (en cualquier formato; ver `references/intake-source-formats.md`) está guardada en el repositorio documental del proyecto.
- [ ] La fuente está clasificada como legible y completa.
- [ ] Cada item del intake tiene etiqueta `origen` (`requested` | `derived`).
- [ ] Cada item del intake tiene etiqueta `validador` (`user` | `dev`).
- [ ] El `cycle-id` está asignado y no choca con un ciclo abierto.
- [ ] El `topic_key` engram está registrado con la observación de intake.
- [ ] La observación de intake está pineada en engram.
- [ ] El roadmap vivo se ha creado a partir de `assets/roadmap.template.md`.

## 1 — Mid-sprint

- [ ] Cada decisión irreversible del sprint tiene su ADR escrito en `docs/<project>/architecture/<topic-slug>.md`.
- [ ] El ADR está referenciado desde el item afectado en el roadmap vivo.
- [ ] El estado de cada item se actualiza en el roadmap vivo en cada commit que lo toca.
- [ ] Cada cambio de estado en el roadmap vivo lleva su `motivo` en una línea.
- [ ] Si se solicitó una snapshot de gestión, se generó con la skill de snapshot del proyecto (no a mano).
- [ ] Si se hizo `mem_session_summary` al cerrar sesión, el `topic_key` del ciclo está incluido.

## 2 — Handoff a UAT

- [ ] Todos los items `requested` tienen criterio de aceptación pactado con el cliente.
- [ ] Todos los items `derived` tienen criterio de aceptación authored por desarrollo e informado al cliente.
- [ ] La skill de UAT del proyecto generó las acceptance webs (user web, dev web o ambas según eje `validador`).
- [ ] Las webs son autocontenidas (un solo archivo, sin servidor, sin dependencias externas).
- [ ] El registro descargable lleva el checksum de los criterios pinneados.
- [ ] Cada criterio es testeable (formato DADO / CUANDO / ENTONCES) y tiene `pasos` reproducibles.

## 3 — UAT firmado

- [ ] Todos los casos de la web de usuario están en estado `passed` y firmados.
- [ ] Todos los casos de la web de desarrollo (si existe) están en estado `passed` y firmados.
- [ ] La firma está fechada y los firmantes tienen nombre (sin cargos).
- [ ] El registro descargable (record + checksum) está archivado junto al ciclo.
- [ ] No queda ningún item en estado `rojo` o `bloqueado`.

## 4 — Archivado

- [ ] El roadmap vivo se copió a `archive/<cycle-id>-final-<YYYY-MM-DD>.md`.
- [ ] El archivo archivado tiene permisos de solo lectura.
- [ ] El roadmap vivo activo se cerró o se reemplazó por uno nuevo.
- [ ] La observación de cierre está guardada en engram con `topic_key` derivado (`<cycle-id>/archived`).
- [ ] Si hay un siguiente ciclo previsto, su `cycle-id` está reservado y su intake source, identificada.

## Anti-patternos detectados en compuerta

Si al cruzar la compuerta detecta alguno de estos síntomas, pare y corrija antes de seguir:

| Síntoma | Acción correctiva |
|---|---|
| Hay un ADR en `proposed` con más de 7 días sin promover | Cierre la decisión (aceptada o rechazada) o reabra la discusión |
| Un item cambió de estado sin `motivo` | Añada el motivo; el estado sin motivo es reject (HR-11) |
| El roadmap vivo diverge del último commit que afecta a un item | Reconcilie antes de la próxima snapshot |
| Hay items `requested` sin etiqueta `validador` | Clasifique antes de la fase UAT (HR-6) |
| La firma de UAT cita criterios distintos de los pinneados | Rehaga la firma con la versión pinneada; un criterio nuevo exige un ADR |