# Proposal: Correct Pre-Adoption Legacy Provenance

> **CANCELLATION SCOPE (2026-07-10).** This change cancels SDD `adopt-02-expiry` and
> issue #48 for invalid legacy provenance. The 20-day decision clause belongs to foster care
> (`APAP_ACTUAL/src/classes/Plantilla.cls`, `RellenarContratoAcogida`, lines 381-391), NOT to
> pre-adoption expiry. Pre-adoption remains active until definitive adoption or explicit
> return, governed by `FDevolucion IS NULL` (`Adopcion.cls`, `AnimalConAdopcionesActivas`,
> lines 1991-2054). See `CANCELLATION.md` for forensic retention.

## Intent

Correct the false legacy-parity claim that pre-adoptions expire automatically after 20 days. The 20-day clause belongs to foster care (`Plantilla.RellenarContratoAcogida`); pre-adoption remains active until definitive adoption or explicit return, with the runtime registry selecting the same `CONTRATO DE ADOPCIÓN_V02.docx` (`Entorno.cls` L793) for both Adopción and PreAdopción, and `RellenarContratoPreAdopcion` (`Plantilla.cls` L620-689) producing a sex-conditional sterilization text — no runtime timer, no automatic expiry. Any expiry automation is a new product decision requiring explicit approval.

## Scope

### In Scope
- Correct APAP_WEB discovery, state-machine, architecture, roadmap, and README references using exact legacy evidence.
- Mark issue #48 and SDD `adopt-02-expiry` cancelled for invalid provenance, retaining branch, stash, OpenSpec, and Engram traceability.
- Preserve ADOPT-01: `TipoAdopcion`, manual contracts/follow-up, sterilization and formalization, and return only through `FDevolucion`.
- Assess equivalent APAP_ACTUAL docs and record the need for a separate repository PR without editing that repository.

### Out of Scope
- Product code, migrations, expiry jobs, notifications, or tests.
- Cherry-picking or reproducing the invalid local implementation.
- Deciding or implementing a future expiry policy.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `migration-discovery-docs`: Require corrected, source-proven adoption and contract lifecycle documentation without invented expiry states.

## Approach

Use CodeGraph evidence from `APAP_ACTUAL/src/classes/Plantilla.cls`, `APAP_ACTUAL/src/classes/Adopcion.cls`, and `APAP_ACTUAL/src/modules/Funciones Generales.bas`, plus contract-template evidence, as the provenance baseline. Replace the foster/pre-adoption misattribution, remove invented `Vencido` and timer claims, and add explicit cancellation links. Targeted searches will prove consistency. APAP_ACTUAL contains equivalent false references and therefore needs its own later PR.

## Affected Areas

| Area | Impact | Description |
|---|---|---|
| `docs/discovery/` | Modified | Correct clauses, lifecycle, and model claims |
| `docs/architecture/architecture-insforge-stack.md` | Reviewed/Modified | Remove any derived worker premise |
| `docs/roadmap.md`, `README.md` | Modified | Cancel ADOPT-02/#48 premise |
| `openspec/changes/adopt-02-expiry/`, Engram | Modified | Add cancellation traceability; retain evidence |
| `C:/00repos/codigo/APAP_ACTUAL/docs/` | External | Separate PR required; no edits here |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Removing valid adoption behavior | Medium | Preserve ADOPT-01 and `FDevolucion` invariants explicitly |
| Incomplete correction | Medium | Search both repositories for expiry variants |

## Rollback Plan

Revert only the corrective documentation commit; preserve forensic branch, stash, and Engram history. Do not restore invalid implementation.

## Dependencies

- APAP_ACTUAL source and contract-template evidence; issue #48 history.

## Success Criteria

- [ ] APAP_WEB docs consistently distinguish the foster 20-day clause from pre-adoption lifecycle.
- [ ] Issue #48 and `adopt-02-expiry` are traceably cancelled without evidence deletion.
- [ ] Targeted searches and CodeGraph show no automatic pre-adoption expiry claim; no product-code tests run unless code changes.

## Proposal Question Round

Assumption for review: cancellation is documentation-only; any future timer starts as a separately approved business change.
