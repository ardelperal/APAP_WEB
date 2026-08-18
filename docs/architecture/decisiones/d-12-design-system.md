# D-12 — Design system reutilizable

## Decision

Pendiente de issue #6 ("feat(ux): definir la base UX/UI de APAP"). Hasta que se implemente, la UI se construye con tokens ad-hoc heredados de [`design-tokens-apap-actual.md`](../design-tokens-apap-actual.md) (referencia del legacy).

## Quick path

- Status: pendiente, sin ADR de implementación definido.
- Mientras esté pendiente, la UI usa tokens ad-hoc documentados en [`design-tokens-apap-actual.md`](../design-tokens-apap-actual.md).
- Cuando se implemente, se reemplazará esta ADR por D-DS-01 con el sistema de diseño concreto.

## Problem statement

Sin design system, cada pantalla nace con su propio espaciado, color y tipografía. Esto genera inconsistencia visual, fricción de mantenimiento y难以 hacer evoluciones globales (cambiar un color exige tocar docenas de archivos). El refugio merece una base de UI coherente, no un collage de estilos heredados.

## Evidence and scope

- Issue #6 ("feat(ux): definir la base UX/UI de APAP") sigue abierta.
- [`design-tokens-apap-actual.md`](../design-tokens-apap-actual.md) documenta los tokens ad-hoc vigentes.
- [`openspec/changes/ux-ui-foundation/`](../../openspec/changes/ux-ui-foundation/) trabaja la fundación UX pendiente.
- [`decisiones-proyecto.md` § D-11](decisiones-proyecto.md) fija que la UI no es skin del Access.

## Options considered

| Opción | Pros | Contras |
|---|---|---|
| Implementar design system propio (a evaluar) | Encaja con APAP; sin dependencias externas. | Trabajo inicial alto. |
| Adoptar Mistica de Telefónica (a evaluar) | Robusto; alineado con Telefónica (audiencia). | Curva de aprendizaje; acoplamiento a un sistema externo. |
| Mantener tokens ad-hoc (status quo) | Cero inversión inmediata. | Inconsistencia; deuda que crece con cada pantalla. |

## Goals

- Componentes UI reutilizables con tokens centralizados.
- Una sola fuente de verdad para color, tipografía, espaciado.
- Cambios globales de estilo sin tocar cada pantalla.

## Non-goals

- Internacionalización de copy (cubierto por D-10).
- Reescritura completa de pantallas existentes en este PR.
- Definir un sistema de motion design en este alcance.

## Non-negotiable invariants

- **Regla D-10**: copy en castellano peninsular.
- **Regla D-11**: UI moderna, no skin del Access.
- **Regla D-37**: identificadores técnicos en inglés.

## Consequences

- Mientras esté pendiente, los tokens ad-hoc en [`design-tokens-apap-actual.md`](../design-tokens-apap-actual.md) son la base.
- Cada PR de UI nueva verifica que los tokens usados están en [`design-tokens-apap-actual.md`](../design-tokens-apap-actual.md) o propone su inclusión.
- La implementación del design system cierra esta ADR y abre D-DS-01.

## When this changes

- Cuando se implemente el design system (cierre de #6), esta ADR se reemplaza por D-DS-01 con la decisión concreta.
- Si se decide adoptar Mistica u otra librería externa, se documenta como D-DS-01 con la justificación.