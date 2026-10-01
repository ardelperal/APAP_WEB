---
name: ci-pattern-incidents
description: "Ejemplo destilado de hotfix y post-mortem blameless sobre un incidente real de pérdida de datos (Cadete, 2026-09-23). Patrón de referencia para HR-19 a HR-22; no es el RCA completo."
---

# Incidents — ejemplo destilado: pérdida de datos (Cadete, 2026-09-23)

Este doc es el patrón de ejemplo de la capa release/hotfix/post-mortem
(HR-19 a HR-22). Es una destilación, no el RCA completo: el post-mortem íntegro
vive en el repositorio del consumer, bajo `docs/postmortems/`.

## Resumen del incidente

- **Fecha**: 2026-09-23. Consumer: Cadete (OpenShift/Quay).
- **Causa raíz (sistema, blameless)**: un `initContainer` con `rm -rf` sobre el
  PVC se re-ejecutó en un reapply del manifiesto y borró los datos.
- **Impacto**: pérdida de datos; la restauración la hizo IT a mano.
- **Brecha real detectada**: no existían backups automatizados; la recuperación
  dependía de intervención manual.

## Flujo aplicado (lo que el patrón exige)

1. Issue canónica (`type:bug`) con la evidencia del incidente.
2. Fix aterrizado en main por el pipeline normal: eliminación declarativa del
   `initContainer` en el YAML.
3. Deploy inmediato tras el merge.
4. Release hotfix `v1.0.0`: tag anotado, GitHub Release marcada `Latest` y
   notas concisas que enlazan al issue; el RCA nunca vivió dentro de las notas.
5. Post-mortem blameless en `docs/postmortems/` del consumer con secciones
   Timeline (UTC) / Impact / Root cause / What worked / What failed; causas de
   sistema, sin personas.
6. Action items abiertos como issues de GitHub con owner: automatización de
   backups de MySQL como brecha sistémica.

## Lecciones que generaliza

- Un `initContainer` destructivo es código de producción, no bootstrap
  inofensivo: cualquier reapply puede volver a ejecutarlo.
- La brecha no fue el `rm -rf` aislado sino la ausencia de backups automatizados;
  el action item debe atacar la brecha sistémica, no el síntoma.
- Fix, deploy y release PATCH salieron el mismo día; el post-mortem y sus
  action items cerraron el ciclo con evidencia trazable al SHA desplegado.
