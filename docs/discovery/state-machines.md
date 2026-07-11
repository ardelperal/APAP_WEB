# State Machines

Cross-cutting reference for all state machines across APAP features. Each machine documents the states, allowed transitions, trigger events, and integration points with other features.

## 1. Animal Lifecycle State Machine

The animal's current situation (`Situacion`) is a computed state derived from active records across intake, foster, and adoption tables. It is **not** manually set.

> **Derivation source:** Feature 01 — `docs/discovery/feature-01-animal-lifecycle.md` § "Computed state model"

### States

| State | Meaning | Terminal? |
|-------|---------|-----------|
| Pendiente de Entrada | Intake registered but not yet completed | No |
| Pendiente de Nueva Situación | Previous situation ended; awaiting next action | No |
| Albergue | Animal physically in shelter | No |
| Acogida | Animal placed in foster care | No |
| Adoptado | Animal permanently adopted | No |
| Entregado | Returned to owner | Yes (normal flow) |
| Fallecido | Deceased | Yes |
| Eutanasia | Euthanized | Yes |
| Incoherente | Data inconsistency detected | Yes |

### Transition rules

| From | Allowed next states | Trigger event |
|------|---------------------|---------------|
| Pendiente de Entrada | Albergue, Acogida, Adoptado, Fallecido | Intake completion (animal placed) |
| Pendiente de Nueva Situación | Albergue, Acogida, Adoptado, Fallecido | New placement action |
| Albergue | Acogida, Adoptado, Fallecido | Foster assignment, adoption, or death registration |
| Acogida | Adoptado, Fallecido, Pendiente de Nueva Situación | Adoption from foster, death, or foster return |
| Adoptado | Acogida, Fallecido, Pendiente de Nueva Situación | Return from adoption (re-entry), death, or return to owner |
| Entregado | — | Terminal for normal flow |
| Fallecido / Eutanasia | — | Terminal; no normal actions |
| Incoherente | — | Terminal; requires manual data correction |

### State derivation rules

| Active record condition | Derived state |
|------------------------|---------------|
| `TbEntradas` with no completion | Pendiente de Entrada |
| `TbAcogidaAnimal` with no end date | Acogida |
| `TbAdopcion` with no return date | Adoptado |
| `TbEntradas` completed, no active foster/adoption | Albergue |
| `FDefuncion` = True on `TbAnimales` | Fallecido |
| `Eutanasia*` flags set on `TbAnimales` | Eutanasia |
| None of the above | Pendiente de Nueva Situación |

### Timeline and audit trail requirement

Every state transition in the Animal Lifecycle machine MUST be recorded as a timestamped event in the animal's lifecycle event log. The state itself is derived from the most recent event — never stored independently.

| Principle | Rule |
|-----------|------|
| Event-first | A state change is only valid if it originates from a recorded event (intake, foster placement, adoption, return, death, etc.) |
| Chronological continuity | The event log MUST represent unbroken continuity: every interval between events has a known location/arrangement |
| Gap flagging | Timeline gaps (unknown location/arrangement for an interval) are flagged as data-quality defects for manual resolution |
| Terminal enforcement | No events are permitted after a death/euthanasia entry in the timeline |
| Legacy migration | Migrated records with partial or conflicting history are flagged with `legacy_gap` or `incoherente` markers |

This timeline is the **single source of truth** for an animal's history. Queries like "where was animal X on date Y?" or "how many times was animal X in foster?" are answered from the event log, not from computed state.

See `feature-01-animal-lifecycle.md` § "Lifecycle Event Timeline and Location Traceability" for the full event type inventory and migration rules.

### Integration points

- **Foster stays** (`TbAcogidaAnimal`) directly drive the Acogida state. An active foster stay with no `FFinal` date places the animal in Acogida.
- **Adoptions** (`TbAdopcion`) directly drive the Adoptado state. An active adoption with no `FDevolucion` date places the animal in Adoptado.
- **Health actions** (`TbActuacionSanitaria`) do **not** affect lifecycle state, but date validation (`FechaAnotacion` must be within animal lifespan) depends on the death date from this machine.
- **Contracts** (`TbContratosAnexos`) are generated per workflow event (intake, foster, adoption) and do not drive state transitions.

## 2. Foster Home Status State Machine

Tracks the operational status and capacity of each registered foster home.

### States

| State | Meaning |
|-------|---------|
| Activa | Home is available and accepting animals |
| Inactiva | Home is not accepting animals (paused, withdrawn, or unavailable) |
| Capacidad Excedida | Home has more active placements than declared capacity |

### Transition rules

| From | Allowed next states | Trigger event |
|------|---------------------|---------------|
| Activa | Inactiva | Foster parent requests pause/withdrawal; admin disables |
| Activa | Capacidad Excedida | Active placement count exceeds declared capacity |
| Inactiva | Activa | Foster parent reactivates; admin re-enables |
| Capacidad Excedida | Activa | Placement count drops to or below capacity (animal returns or is adopted) |
| Capacidad Excedida | Inactiva | Foster parent requests pause while over capacity |

### Capacity computation

| Rule | Detail |
|------|--------|
| Current count | Active foster stays (`TbAcogidaAnimal`) with `FFinal IS NULL` for the home |
| Max capacity | Declared on `TbAcogidaCasas` registration |
| Species filter | Capacity check considers species preference (CANINA / FELINA) |
| Enforcement | **Open question:** Hard block at assignment time vs. advisory only (see `open-decisions.md`) |

### Integration points

- **Animal lifecycle:** When an animal enters foster care, the foster home's occupied count increments. When the foster stay ends (return, adoption, death), the count decrements.
- **Capacity state** is derived, not manually set. A home enters Capacidad Excedida when `COUNT(active stays) > max capacity`.

## 3. Contract Lifecycle State Machine

Contracts are generated per workflow event (intake, foster, adoption, surrender) and follow a lifecycle from draft to signed (no automatic expiry).

### States

| State | Meaning |
|-------|---------|
| Borrador | Template selected and document generated; not yet saved |
| Pendiente de Firma | Document saved; awaiting signature from parties |
| Firmado | Contract signed and registered in `TbContratosAnexos` |
| Anulado | Contract voided or cancelled |

### Transition rules

| From | Allowed next states | Trigger event |
|------|---------------------|---------------|
| Borrador | Pendiente de Firma | Document saved to system |
| Pendiente de Firma | Firmado | All parties sign; registration in `TbContratosAnexos` |
| Pendiente de Firma | Anulado | Parties withdraw; admin cancels |
| Firmado | Anulado | Contract voided (rare; legal/admin action) |
| Anulado | — | Terminal; new contract may be generated if needed |

### Contract types and their lifecycle specifics

| Contract type | Workflow context | Signature requirement | Expiry rule |
|---------------|------------------|----------------------|-------------|
| Entrada | Intake | Intake volunteer + delivery person | None |
| Acogida | Foster | Foster parent + association rep | Tied to foster stay duration |
| Acogida Judicial | Judicial foster | Court-appointed + association rep | Tied to judicial order |
| Adopción | Adoption | Adopter + association rep | None (permanent) |
| PreAdopción | Pre-adoption | Adopter + association rep | None (manual close via definitive adoption or return through FDevolucion) |
| Cesión por Propietario | Owner surrender | Surrendering owner + association rep | None |
| Reserva de Adopción | Adoption reservation | Adopter + association rep | Reservation window |
| Entrega a Propietario | Return to owner | Owner + association rep | None |

### Integration points

- **Animal lifecycle:** Contract generation is triggered by workflow events (intake completion, foster assignment, adoption registration). The contract does not drive state transitions.
- **Species/sex/age conditionals:** Template selection and clause inclusion depend on animal attributes from the lifecycle state (species, sex, age). See Feature 04 § "Contract conditional clauses by type".

## 4. Health Action Status State Machine

Individual health actions do not have a multi-state lifecycle in the legacy system. They are recorded and immutable. However, the **batch staging** workflow has a distinct state model.

### Single health action states

| State | Meaning |
|-------|---------|
| Registrada | Health action recorded and committed to `TbActuacionSanitaria` |

A single health action transitions directly from "not yet recorded" to "Registrada" on commit. There is no draft/pending state for individual actions.

### Batch health action staging states

| State | Meaning |
|-------|---------|
| En Borrador | Staged in `TbActuacionSanitariaAux`; not yet validated |
| Validada | All staged records pass validation; ready for commit |
| Rechazada | One or more staged records failed validation; batch rejected |
| Commiteada | All records committed to `TbActuacionSanitaria`; staging cleared |

### Transition rules (batch)

| From | Allowed next states | Trigger event |
|------|---------------------|---------------|
| En Borrador | Validada | All staged records pass date range, duplicate, and puppy-test validation |
| En Borrador | Rechazada | Any staged record fails validation |
| Validada | Commiteada | User confirms commit; all-or-nothing write to production table |
| Rechazada | En Borrador | User corrects errors and resubmits |

### Integration points

- **Animal lifecycle:** Health action date validation depends on the animal's birth date (`FNacimiento`) and death date (`FDefuncion`) from the lifecycle state machine.
- **Upcoming tasks engine:** The periodicity engine (`TbPruebasPeridicidad` + `TbNombrePruebas`) computes due dates based on last recorded action date. A committed health action updates the "last action" reference for that test type.

## 5. Adoption Follow-Up State Machine

Tracks the post-adoption follow-up process: document delivery, attachment, and completion.

### States

| State | Meaning |
|-------|---------|
| Pendiente | Adoption registered; follow-up documents not yet delivered |
| Documento Entregado | Follow-up document delivered to adopter |
| Documento Adjunto | Adopter has returned the signed document; attached to record |
| Seguimiento Completado | Follow-up process fully closed |

### Transition rules

| From | Allowed next states | Trigger event |
|------|---------------------|---------------|
| Pendiente | Documento Entregado | Follow-up document sent to adopter |
| Documento Entregado | Documento Adjunto | Adopter returns signed document; staff attaches it |
| Documento Adjunto | Seguimiento Completado | Staff marks follow-up as complete |
| Pendiente | Seguimiento Completado | Direct completion (if no follow-up document required) |

### Integration points

- **Animal lifecycle:** Adoption follow-up status does not affect the animal's `Situacion` state. The animal remains in Adoptado state throughout the follow-up process.
- **Contracts:** The adoption contract is generated at adoption registration, before follow-up begins. Follow-up documents are separate from the adoption contract.
- **Attachments:** Follow-up documents are stored as attachments (`TbDocumentosAnexos`) linked to the adoption record.

## Cross-machine integration summary

| Source machine | Target machine | Integration point |
|----------------|----------------|-------------------|
| Animal Lifecycle | Foster Home Status | Active foster stay increments/decrements home capacity |
| Animal Lifecycle | Contract Lifecycle | Workflow events trigger contract generation |
| Animal Lifecycle | Health Action Status | Birth/death dates bound health action date validation |
| Animal Lifecycle | Adoption Follow-Up | Adoption state is prerequisite for follow-up |
| Foster Home Status | Animal Lifecycle | Foster assignment/return drives Acogida transitions |
| Health Action Status (batch) | Animal Lifecycle | Batch commit depends on valid animal lifespan |
| Contract Lifecycle | Animal Lifecycle | Contract type determined by workflow context and animal attributes |
