# D-33 — TDD estricto

## Decision

Tests antes de código (excepto `type:docs` y ops puros). Cada unidad de trabajo = 1 issue → test rojo → implementación mínima que lo pone en verde → refactor con tests verdes → integrar → cerrar issue con trazabilidad (commit SHA + test path).

`pytest -W error::DeprecationWarning` corre verde en todo momento. CI gate en `ci / test`.

## Quick path

- Test rojo → código mínimo → verde → refactor.
- 1 issue = 1 unidad de trabajo cohesiva.
- `pytest -W error::DeprecationWarning` siempre verde.

## Problem statement

Sin TDD estricto, los tests se acumulan como tarea pendiente, las regresiones se descubren en producción, y la refactorización se vuelve arriesgada porque no hay red de seguridad. El refugio no tolera regresiones que rompan la operativa diaria; el coste de un bug post-deploy es desproporcionado frente al coste de escribir el test antes.

## Evidence and scope

- Regla histórica del proyecto.
- [`pyproject.toml`](../../pyproject.toml) configura `filterwarnings = ["error::DeprecationWarning"]`.
- [`tests/`](../../tests/) contiene los tests por módulo + smoke + integración.
- CI gate `ci / test` ejecuta `pytest` en cada PR.

## Options considered

| Opción | Pros | Contras |
|---|---|---|
| TDD estricto (aceptada) | Red de seguridad; cobertura implícita; refactor seguro. | Más tiempo por unidad; disciplina del contribuidor. |
| Tests post-hoc (rechazada) | Más velocidad inicial. | Regresiones en producción; cobertura ficticia. |
| Sin tests (rechazada) | Velocidad máxima. | Inviabilidad: cualquier cambio rompe algo. |

## Goals

- 100% de las unidades de trabajo llegan a `main` con tests verdes.
- La cobertura cumple [`codebase/quality-gates.md`](../codebase/quality-gates.md) §19 (80%).
- `DeprecationWarning` se trata como error: cero warnings en el pipeline.

## Non-goals

- Cobertura 100% (se mide por capacidad crítica, no por línea).
- TDD para `type:docs` y ops puros (no aplica).
- Reemplazar TDD por mutation testing (orthogonal, no excluyente).

## Non-negotiable invariants

- **Regla D-30**: trazabilidad por SHA al cerrar issues.
- **Regla D-41**: trazabilidad obligatoria al cerrar issues (incluye test path).

## Consequences

- El flujo por issue es: abrir → test rojo → código → verde → refactor → integrar → cerrar.
- `pytest -W error::DeprecationWarning` es un gate de merge.
- Las PRs sin tests verdes se rechazan en review.
- Los tests viven junto al código (`tests/test_<módulo>.py`).

## When this changes

- Si la cobertura 80% resulta insuficiente, se sube por capacidad crítica.
- Si el equipo crece y el TDD se vuelve cuello de botella, se evalúan técnicas como property-based testing.