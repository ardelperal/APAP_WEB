# Delta for Migration Discovery Documentation

## ADDED Requirements

### Requirement: Source-Proven Legacy Lifecycle Claims

APAP_WEB documentation MUST cite exact legacy source evidence for every parity claim and MUST distinguish contract wording from executable lifecycle behavior. It SHALL state that the 20-day decision clause belongs to foster-contract generation (`APAP_ACTUAL/src/classes/Plantilla.cls`, `RellenarContratoAcogida`, lines 381–391), not pre-adoption expiry. It SHALL document pre-adoption as active until definitive adoption or explicit return, with activity determined by `FDevolucion IS NULL` (`Adopcion.cls`, `AnimalConAdopcionesActivas`, lines 1991–2054), and SHALL accurately cite the pre-adoption contract's sex-conditional sterilization text (template text only — the runtime registry `Entorno.cls` L793 selects the same `CONTRATO DE ADOPCIÓN_V02.docx` for both Adopción and PreAdopción; `RellenarContratoPreAdopcion` `Plantilla.cls` L620-689 contains no one-month or other automatic timer).

#### Scenario: Correct provenance is documented

- GIVEN adoption and contract lifecycle documentation
- WHEN a reviewer follows each legacy-parity citation
- THEN the 20-day clause resolves to foster-contract text and the pre-adoption clause to sex-conditional sterilization text inside the runtime-selected template
- AND executable lifecycle claims resolve to active-record logic rather than contract prose
- AND no claim asserts a runtime timer, worker/cron, or automatic expiry for pre-adoption

#### Scenario: Active pre-adoption remains active

- GIVEN a pre-adoption with no definitive adoption and no `FDevolucion`
- WHEN its legacy lifecycle is documented
- THEN it MUST remain active without any elapsed-time transition
- AND explicit return or definitive adoption MUST be identified as the closing event

### Requirement: Invalid Expiry Premise Removal and Behavior Preservation

Normative APAP_WEB docs, README, and roadmap content MUST NOT claim a `Vencido` state, automatic pre-adoption expiry, timer, worker/cron, or expiry notification. ADOPT-01 behavior—`TipoAdopcion`, manual contracts and follow-up, sterilization/formalization, and return through `FDevolucion`—MUST remain documented and unchanged. Product code from invalid local ADOPT-02 commits MUST NOT enter the deliverable, and code tests SHALL be required only if product code changes.

#### Scenario: Invalid automation claims are removed

- GIVEN the APAP_WEB documentation set
- WHEN targeted searches inspect pre-adoption expiry terminology and automation claims
- THEN no normative automatic-expiry claim remains
- AND legitimate historical or cancellation references MAY remain when explicitly labeled non-operative

#### Scenario: ADOPT-01 regression is prevented

- GIVEN corrected adoption documentation
- WHEN it is compared with the accepted ADOPT-01 contract
- THEN all valid ADOPT-01 behavior remains present
- AND no expiry correction redefines `TipoAdopcion`, follow-up, formalization, or `FDevolucion`

#### Scenario: Invalid product commits are excluded

- GIVEN local commits or stashed work implementing the invalid expiry premise
- WHEN the documentation deliverable is assembled
- THEN no product-code diff from that work is included
- AND no code test is required unless a product-code file changes

### Requirement: Cancellation and Cross-Repository Traceability

Issue #48 and SDD `adopt-02-expiry` MUST be marked cancelled for invalid provenance while retaining forensic links to relevant issue, branch, stash, commits, OpenSpec, and Engram evidence. APAP_ACTUAL documentation correction MUST be recorded as separate-repository work and MUST NOT be edited by this APAP_WEB change.

#### Scenario: Cancellation remains auditable

- GIVEN issue #48 and `adopt-02-expiry` artifacts
- WHEN cancellation is recorded
- THEN each is explicitly cancelled with the provenance reason
- AND retained forensic references allow reconstruction without treating invalid work as deliverable

#### Scenario: External correction is separated

- GIVEN equivalent incorrect claims in APAP_ACTUAL documentation
- WHEN APAP_WEB correction scope is reviewed
- THEN a separate APAP_ACTUAL repository task is recorded
- AND this change contains no APAP_ACTUAL file modification

#### Scenario: Targeted-search acceptance is precise

- GIVEN search hits for expiry-related terms across APAP_WEB docs, README, roadmap, and retained SDD history
- WHEN acceptance is evaluated
- THEN historical and cancellation hits pass only when clearly non-normative
- AND any operative automatic-expiry, timer, worker/cron, or notification claim fails acceptance
