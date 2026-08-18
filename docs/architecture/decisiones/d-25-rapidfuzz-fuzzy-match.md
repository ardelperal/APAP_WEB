# D-25 — Librería de fuzzy match: rapidfuzz (no thefuzz)

## Decision

El pipeline de deduplicación fuzzy de voluntarios legacy (issue #36 / VOL-03) usa `rapidfuzz` (`>=3.0`, current stable 3.14.x) en vez de `thefuzz` (formerly `fuzzywuzzy`).

**Contrato de la API usado**: `rapidfuzz.fuzz.WRatio` (weighted ratio, accent- y case-insensitive) combinado con pre-normalización de diacríticos vía `unicodedata.normalize("NFKD", ...)` + filtrado de `unicodedata.combining(ch)`.

**Threshold por defecto**: 85 (sobre la escala 0..100 de `rapidfuzz`). Configurable por el caller (`dedup_volunteers(refs, fuzzy_threshold=N)`).

## Quick path

- Usar `rapidfuzz` `>=3.0`, stable 3.14.x.
- `WRatio` + pre-normalización NFKD para absorber diacríticos.
- Threshold 85 por defecto, configurable por caller.

## Problem statement

La deduplicación de voluntarios importados del legacy Access requiere fuzzy match (typos, variantes de diacríticos: "María" / "Maria", "García" / "Garcia"). El equipo debe elegir una librería mantenida, sin caer en una deprecada que viole la regla §8 de AGENTS (sin librerías deprecadas).

## Evidence and scope

- Issue #36 (VOL-03, `legacy-discovery-interrogatorio` task 3.2) abre la conversación.
- Validado en sesión 2026-07-27 vía Context7 MCP: `resolve-library-id` + `query-docs` + `websearch`.
- [`pyproject.toml`](../../pyproject.toml) fija `rapidfuzz>=3.0`.
- [`tests/migration/test_volunteer_dedup.py`](../../tests/migration/test_volunteer_dedup.py) cubre la deduplicación.
- [`migration/`](../../migration/) contiene el pipeline.

## Options considered

| Opción | Pros | Contras |
|---|---|---|
| rapidfuzz (aceptada) | Mantenido por el autor de thefuzz; wheels precompilados; 10-50× más rápido que thefuzz. | Curva de API ligeramente distinta. |
| thefuzz / fuzzywuzzy (rechazada) | API conocida. | Abandonado (último release 0.22.1 del 2024-01-19); viola AGENTS §8. |
| jellyfish (rechazada) | Otra opción de match. | Menos rico en algoritmos fonéticos/weighted; menos documentado para el caso. |
| Implementación propia (rechazada) | Control total. | Reinventar la rueda; falta de cobertura de casos raros. |

## Goals

- Deduplicación de voluntarios legacy con tolerancia a typos y diacríticos.
- Threshold configurable, default razonable (85).
- Tests cubren los casos típicos del legacy español.

## Non-goals

- Reemplazar la lógica de match por ML o embeddings.
- Internacionalizar el match a otros alfabetos.
- Sustituir la revisión humana final del operador.

## Non-negotiable invariants

- **Regla §8 de AGENTS** ([`AGENTS.md`](../../AGENTS.md)): sin librerías deprecadas pineadas.
- **Regla D-32**: si código y doc divergen, gana el código y la doc se actualiza en la misma sesión.

## Consequences

- `rapidfuzz` se instala via `uv` como dependencia directa.
- La pre-normalización NFKD es necesaria porque `WRatio` por sí solo puntúa "María García" / "Maria Garcia" en 83 (por debajo del threshold 85); con normalización previa sube a 100.
- El threshold 85 se documenta en [`migration/`](../../migration/) para que callers lo entiendan.
- Los voluntarios deduplicados se reportan al operador con la puntuación, para validación humana final.

## When this changes

- Si `rapidfuzz` deja de mantenerse, se evalúa un sucesor con API similar.
- Si el threshold 85 resulta insuficiente (falsos positivos/negativos), se ajusta por caller, no globalmente.