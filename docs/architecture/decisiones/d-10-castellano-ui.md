# D-10 — Idioma visible en UI: castellano de España

## Decision

Todos los labels, mensajes y textos visibles al usuario final en castellano de España (tildes, ñ, vocabulario peninsular). Esto afecta solo a la UI; los identificadores internos (nombres de campos, nombres de variables, contratos JSON) permanecen en inglés (ver D-37).

## Quick path

- UI visible = castellano de España.
- Identificadores técnicos = inglés.
- Tildes y ñ se conservan; sin latinización.
- Vocabulario peninsular: "vale" no "OK", "buscar" no "search" en botones.

## Problem statement

APAP_WEB sirve a un voluntariado y adoptantes en España. Sin regla explícita, el copy de UI termina siendo una mezcla de traducciones literales del inglés, regionalismos y términos incorrectos ("adopta" usado para cesión, "ficha" usada para dos cosas distintas). El equipo necesita un contrato de idioma que aplique a toda cadena visible.

## Evidence and scope

- Issues #127, #128, #131 cierran la conversación sobre idioma de UI.
- [`app/modules/cesiones/`](../../app/modules/cesiones/) y [`app/modules/sanidad/`](../../app/modules/sanidad/) muestran el patrón copy castellano + identificadores inglés.
- [`tests/test_roles_enum.py`](../../tests/test_roles_enum.py) referencia el contrato.
- [`decisiones-proyecto.md` § D-37](decisiones-proyecto.md) refuerza esta regla a nivel de artefactos.

## Options considered

| Opción | Pros | Contras |
|---|---|---|
| Castellano peninsular en UI (aceptada) | Audiencia objetivo clara; consistencia; sin localismos. | Requiere revisión de copy por hablante nativo. |
| Castellano neutro (rechazada) | Aceptable para audiencia amplia. | Pierde afinidad con el voluntariado peninsular. |
| Inglés en UI (rechazada) | Más rápido. | Desalineado con la audiencia; fricción de uso. |
| Bilingüe (rechazada) | Atiende a dos audiencias. | Duplica trabajo de copy y QA; no aporta al MVP. |

## Goals

- Todo label, mensaje y texto visible está en castellano de España.
- Tildes y eñe se preservan en HTML, JSON y BD.
- Los campos técnicos (nombres de variables, columnas SQL) están en inglés.

## Non-goals

- Internacionalización a otros idiomas (no hay audiencia objetivo fuera de España).
- Latinización de caracteres ("año" → "ano").
- Localización de fechas/moneda al formato anglosajón.

## Non-negotiable invariants

- **Regla D-37**: idioma de artefactos técnicos en inglés.
- **Regla D-11**: UX no es skin del Access (copy es moderno, no legacy).

## Consequences

- Cada PR con cambio de copy pasa por revisión de un hablante nativo de castellano peninsular.
- El linter puede validar la presencia de tildes esperadas en strings de UI (futuro).
- Los mensajes de error y validación se redactan pensando en el voluntariado, no en el desarrollador.

## When this changes

- Si APAP_WEB abre audiencia fuera de España, se crea D-I18N-01 con la estrategia de internacionalización.
- Si el refugio opera con personal de habla no española, se evalúa bilingüismo por sección, no global.