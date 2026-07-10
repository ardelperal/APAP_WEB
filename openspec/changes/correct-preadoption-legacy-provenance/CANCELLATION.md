# Cancellation Notice — SDD `adopt-02-expiry`

**Date:** 2026-07-10
**Cancelling change:** `correct-preadoption-legacy-provenance`
**Reason:** Invalid legacy provenance. The 20-day decision clause belongs to foster care
(`APAP_ACTUAL/src/classes/Plantilla.cls`, `RellenarContratoAcogida`, lines 381-391), NOT to
pre-adoption lifecycle. Pre-adoption remains active until definitive adoption or explicit
return, governed by `FDevolucion IS NULL` (`Adopcion.cls`, `AnimalConAdopcionesActivas`,
lines 1991-2054). No automatic expiry, no timer, no worker, no notification.

## Forensic retention (NOT delivered)

| Artifact | State | Location |
|---|---|---|
| `feat/adopt-02-expiry` branch | KEPT at `40ce83f` (not deleted) | local git |
| `stash@{0}: adopt-02-invalid-work-2026-07-10` | KEPT (not popped, not dropped) | local git stash |
| Local-main 3 invalid commits (`2ea1765`, `be43c14`, `40ce83f`) | KEPT ahead of `origin/main` | local `main`; not cherry-picked into this change |
| `openspec/changes/adopt-02-expiry/` OpenSpec tree | KEPT on `feat/adopt-02-expiry` | not present on `docs/correct-preadoption-legacy-provenance` |
| GitHub issue #48 | Cancelled with provenance reason | `gh issue comment` posted by apply phase |
| Engram (5 topic keys) | `superseded` / `cancellation` notes | apply phase `mem_save` |

## ADOPT-01 invariants preserved (NOT changed by this cancellation)

1. `TipoAdopcion` enum (regular / preadopcion / judicial)
2. Manual contracts and follow-up (no automation)
3. Sterilization commitment and formalization (`donativo_preadopcion` / `donativo_adopcion`)
4. Return through `FDevolucion` only (no state derivation from elapsed time)

## External follow-up (NOT in this change)

`APAP_ACTUAL/docs/` contains equivalent false references and requires a separate repository PR
(see design §8).
