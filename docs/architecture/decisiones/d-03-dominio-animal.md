# D-03 — Dominio centrado en Animal

## Decision

Animal es la entidad pivotante. Fichas, timeline, salud, terapias, contratos y adopciones cuelgan de él. Esto refleja la operativa real de la protectora y la estructura del legacy.

## Quick path

- Animal es la raíz del modelo de dominio.
- Cualquier recurso nuevo debe justificarse como colgante de Animal o tener su propio ADR equivalente.
- El modelo de dominio sigue pivote-sobre-Animal aunque el modelo de datos legacy sea multi-tabla.

## Problem statement

El legacy Access distribuía el "animal" en varias tablas (TbFichaAnimal, TbActuacionesSanitarias, TbAdopciones, etc.) sin una FK explícita fuerte. Esto generaba ambigüedad: ¿una actuación cuelga de Animal o de TbFichaAnimal? APAP_WEB debe tener una sola raíz de pivote para evitar la misma fragmentación.

## Evidence and scope

- [`discovery/feature-01-animal-lifecycle.md`](../discovery/feature-01-animal-lifecycle.md) define Animal como entidad pivotante.
- [`legacy-lifecycle-transition-rules.md`](../legacy-lifecycle-transition-rules.md) documenta cómo el legacy gestiona la unidad animal.
- [`roadmap.md`](../roadmap.md) § Fases 4, 5, 6 y 7 parten del pivote Animal.
- Las tablas `animales`, `actuaciones_sanitarias`, `contratos`, `adopciones` se referencian en [`app/core/insforge.py`](../../app/core/insforge.py) con `animal_id` como FK principal.

## Options considered

| Opción | Pros | Contras |
|---|---|---|
| Animal pivotante (aceptada) | Refleja la operativa; una sola fuente de verdad para "el animal". | Requiere re-mapeo del legacy multi-tabla a un pivote único. |
| Persona pivotante (rechazada) | Encaja con workflows centrados en adoptantes. | Desalineado con la operativa del refugio, donde el animal es la unidad de cuidado. |
| Multi-pivote (rechazada) | Más flexible. | Reproduce la fragmentación del Access; dificulta queries. |

## Goals

- Una query sobre un animal da acceso a todo su historial.
- Las migraciones legacy respetan el pivote Animal aunque vengan de varias tablas.
- El lenguaje ubiquitario del dominio pivota sobre Animal (ver [`codebase/architecture.md`](../codebase/architecture.md) §33).

## Non-goals

- Modelar Animal como agregación de partes (cabeza, cuerpo, etc.).
- Reemplazar la gestión multi-tabla del Access en esta release.
- Cambiar los workflows del refugio.

## Non-negotiable invariants

- **Regla D-05**: las capacidades legacy se conservan; si una capacidad legacy no cuelga de Animal, se documenta como gap-of-fidelity.
- **Regla D-04**: paridad de campos obligatorios con el legacy por capacidad, no por tabla.

## Consequences

- El DAO de Animal absorbe queries de las tablas legacy TbFichaAnimal, TbFichaTecnica, TbActuaciones.
- Los módulos de salud, contratos y adopciones (Fases 4-7) se diseñan como colgantes del animal.
- El equipo usa "el animal" como unidad de medida en tickets y PRs.

## When this changes

- Si el refugio abre una línea de trabajo "cuidado por manada" (no por animal individual), se abre una nueva ADR que justifique el cambio de pivote.
- Si el modelo legacy tiene una capacidad que NO cuelga de Animal, se documenta como gap-of-fidelity (D-05) y se crea un ADR específico para esa capacidad.