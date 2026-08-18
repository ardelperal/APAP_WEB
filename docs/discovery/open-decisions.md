# Open Decisions

Unresolved design decisions that affect the web application's business behavior, data model, or feature scope. Each decision requires stakeholder input before implementation.

## Decision 1 — State Derivation Formula

| Field | Detail |
|-------|--------|
| **Status** | Direction decided; schema is implementation decision |
| **Owner** | Product owner / data architect |
| **Deadline** | Before Feature 01 web implementation |
| **Impact** | Animal state resolver service design |

### Decision statement

The animal's `Situacion` field is derived from active records across intake, foster, and adoption tables. The exact derivation logic — whether it is a single SQL query, a multi-step computation, or a priority cascade — is not fully documented.

### Decided direction

The future web model must store an **auditable event timeline** (lifecycle event log) as the single source of truth for an animal's history. The current state is always derived from the most recent event in this timeline. This is a mandatory stakeholder requirement, not an open question.

What remains open is the **exact schema implementation** of the event log table — whether it uses a single normalized table, an event-sourcing pattern, or a hybrid approach. This is an implementation decision, not a business-rule decision.

See `feature-01-animal-lifecycle.md` § "Lifecycle Event Timeline and Location Traceability" for the full requirement.

### Options (for schema implementation only)

| Option | Tradeoff |
|--------|----------|
| **A. Single normalized event table** | Simple; one table with timestamp, event type, actor, location, reference IDs |
| **B. Event-sourcing pattern** | Full replay capability; higher complexity; may be overkill for this domain |
| **C. Hybrid: event log + materialized current state** | Best read performance; requires sync logic between log and materialized state |

### Recommended approach

Option C (hybrid) is recommended: event log as source of truth, materialized current-state cache for read performance. The state derivation logic reads from the event log; a background job or write-path updater maintains the materialized cache.

### Resolution needed

- [ ] Confirm which records take priority when multiple active records exist (e.g., foster + adoption simultaneously)
- [ ] Confirm whether `Incoherente` state is auto-detected or manually assigned
- [ ] Confirm exact query logic from legacy VBA source export
- [ ] Finalize event log schema design (table structure, indexes, retention)

---

## Decision 2 — Strict Mode / Date Validation Business Meaning

| Field | Detail |
|-------|--------|
| **Status** | Open |
| **Owner** | Product owner |
| **Deadline** | Before Feature 03 web implementation |
| **Impact** | Health action date validation behavior in web app |

### Decision statement

Health action dates must fall within the animal's lifespan (birth date to death date). The legacy system enforces "strict mode" where both bounds are hard blocks when a death date exists. The open question is: what happens when the death date is unknown?

### Options

| Option | Tradeoff |
|--------|----------|
| **A. Allow dates after today when no death date** | Flexible; may allow future-dated errors |
| **B. Always require death date before recording post-death actions** | Strict; forces data completeness; may block legitimate workflows |
| **C. Allow post-death date only with explicit override** | Balanced; requires audit trail for overrides |

### Recommended approach

Option A with warning: allow dates after today when death date is unknown, but display a warning. Hard block only on the birth-date lower bound (no action before birth). This matches real-world workflows where health data may be back-dated.

### Resolution needed

- [ ] Confirm whether the legacy system allows health actions with future dates
- [ ] Confirm business rule for death-date-unknown scenarios
- [ ] Confirm whether strict mode is a user-configurable setting or always-on

---

## Decision 3 — Foster Capacity Enforcement

| Field | Detail |
|-------|--------|
| **Status** | Open |
| **Owner** | Product owner / operations lead |
| **Deadline** | Before Feature 02 web implementation |
| **Impact** | Foster home assignment workflow |

### Decision statement

The legacy system tracks foster home capacity but does not enforce it at write time. The web app should validate capacity on assignment. The open question is: should this be a hard block (prevent assignment) or advisory (warn but allow)?

### Options

| Option | Tradeoff |
|--------|----------|
| **A. Hard block at assignment time** | Prevents over-capacity; may disrupt urgent placements |
| **B. Advisory warning with override** | Flexible; requires audit trail for overrides |
| **C. Hard block for regular foster; advisory for emergency** | Context-aware; more complex to implement |

### Recommended approach

Option B (advisory with override) is recommended. Foster homes sometimes have emergency placements. The web app should warn when capacity is exceeded but allow override with a mandatory reason field and audit trail.

### Resolution needed

- [ ] Confirm whether emergency foster placements exist as a formal workflow
- [ ] Confirm whether capacity is per-species or combined
- [ ] Confirm whether the association has a formal over-capacity approval process

---

## Decision 4 — Dynamic Report SQL Security / Product Replacement

| Field | Detail |
|-------|--------|
| **Status** | Open |
| **Owner** | Product owner / security architect |
| **Deadline** | Before Feature 04 web implementation |
| **Impact** | Custom report feature design; security model |

### Decision statement

The legacy system stores arbitrary SQL in the database and executes it directly. This is a significant security risk. The web app must replace this with a safe alternative. The open question is: which replacement approach?

### Options

| Option | Tradeoff |
|--------|----------|
| **A. Curated report templates** | Safe; limited flexibility; requires maintenance for new reports |
| **B. Visual query builder** | User-friendly; high development effort; good for power users |
| **C. Sandboxed SQL execution** | Maximum flexibility; complex to secure; audit required |
| **D. Curated templates + query builder** | Balanced; covers most use cases; moderate effort |

### Recommended approach

Option D (curated templates + query builder) is recommended. Curated templates cover the 80% case (quarterly reports, standard queries). A query builder covers ad-hoc needs without raw SQL exposure. This avoids the security risk of sandboxed execution.

### Resolution needed

- [ ] Confirm which reports are used daily/weekly/quarterly (prioritize template coverage)
- [ ] Confirm whether power users need ad-hoc query capability
- [ ] Confirm whether report execution requires audit logging

---

## Decision 5 — ARIAC/RIAC Scope

| Field | Detail |
|-------|--------|
| **Status** | Open |
| **Owner** | Product owner / regulatory lead |
| **Deadline** | Before Feature 01 web implementation |
| **Impact** | Regulatory communication module scope |

### Decision statement

ARIAC (Asociación Regional de Inspectores Oficiales de Sanidad Animal) and RIAC (Registro de Inspección de Animales de Compañía) are regulatory bodies that require notifications at certain lifecycle events. The legacy system tracks ARIAC notification status via a flag. The open question is: should the web app include a regulatory communication module, or handle this externally?

### Options

| Option | Tradeoff |
|--------|----------|
| **A. Include ARIAC/RIAC module in web app** | Full tracking; higher scope; may require regulatory API integration |
| **B. Track only notification status (flag)** | Minimal; matches legacy behavior; no regulatory integration |
| **C. External integration via webhook/API** | Clean separation; requires external system availability |

### Recommended approach

Option B (track notification status only) is recommended for initial web app. The ARIAC/RIAC notification process is likely manual (letter/email) and external. The web app should track whether notification was sent and when, but not generate the notification itself. This can be extended to Option C in a later phase.

### Resolution needed

- [ ] Confirm whether ARIAC/RIAC notifications are manual or system-generated
- [ ] Confirm which lifecycle events require notification (death, euthanasia, intake, adoption?)
- [ ] Confirm whether regulatory reporting is a product requirement or external process

---

## Decision 6 — Photo/Attachment Volume and Storage Sizing

| Field | Detail |
|-------|--------|
| **Status** | Open |
| **Owner** | Infrastructure / product owner |
| **Deadline** | Before infrastructure provisioning |
| **Impact** | Object storage costs; upload performance; backup strategy |

### Decision statement

The legacy system stores photos and attachments on the local filesystem. The web app must migrate to object storage. The open question is: what is the expected volume, and how should storage be sized?

### Options

| Option | Tradeoff |
|--------|----------|
| **A. Estimate from legacy file system** | Data-driven; requires scanning legacy paths |
| **B. Conservative estimate (100MB per animal)** | Simple; may over-provision |
| **C. Growth model based on intake rate** | Accurate; requires historical data analysis |

### Recommended approach

Option A (estimate from legacy) is recommended. Scan the legacy filesystem to measure actual photo/attachment volume per animal, then add 20% growth buffer. This gives a concrete baseline for storage provisioning.

### Resolution needed

- [ ] Confirm total photo/attachment count and size in legacy filesystem
- [ ] Confirm average photos per animal (estimate: 2–5 photos per animal)
- [ ] Confirm attachment types (photos, PDFs, Word documents, scans)
- [ ] Confirm retention policy (永久 vs. time-limited)

---

## Decision 7 — Volunteer Registry (New Feature)

| Field | Detail |
|-------|--------|
| **Status** | Direction decided (create registry); business rules clarified; implementation details open |
| **Owner** | Product owner / data architect |
| **Deadline** | Before Feature 02 web implementation |
| **Impact** | Target ERD, migration strategy, intake/foster/adoption/health features |

### Decision statement

The legacy system stores volunteer names as free-text strings across multiple tables (`TbEntradas.VoluntarioEntrada`, `TbAdopcion.VoluntarioSeguimiento`, `TbAcogidaAnimal.VoluntarioSeguimiento1/2`, `TbAcogidaAnimal.VoluntarioAcogida`, `TbAcogidaAnimal.VoluntarioCositicasSanitarias`). There is no stable volunteer ID, no deduplication, and no single source of truth. A `TbVoluntariosParaAutorrellenables` table exists but is only a combobox fill source, not a normalized entity.

The stakeholder has confirmed: the web app should have a volunteer registry analogous to the foster home registry. This is a **new feature** that changes the target ERD.

### Decided direction

Create a `Volunteer` first-class entity with stable ID. Existing free-text volunteer fields in intake, foster, adoption, and therapy tables become FK references to `Volunteer.ID`. Legacy text values must be deduplicated/matched into volunteer records during migration.

### Mandatory business rules (clarified)

| # | Rule | Detail |
|---|------|--------|
| BR1 | **FK-only references** | No workflow may assign a volunteer unless that volunteer already exists in the Volunteer Registry. Free-text assignment is prohibited in all target tables. |
| BR2 | **Existence + active validation** | Every create/edit workflow that assigns a volunteer must validate that the volunteer exists and is active. Inactive volunteers cannot be assigned to new records. |
| BR3 | **No physical delete** | A volunteer referenced by ANY business record (intake, foster stay, adoption, therapy, or any other operational table) must not be physically deleted. Only deactivation (soft-delete / mark inactive) is permitted. |
| BR4 | **Historical preservation** | When a volunteer is deactivated, all historical records referencing that volunteer must preserve the FK relationship. The volunteer remains readable for reporting and audit trails. |
| BR5 | **Unreferenced deletion** | A volunteer never referenced by any business record may be deleted, but ONLY if product explicitly decides this. Default policy: deactivation for all. |

### Open implementation decisions

| # | Question | Options | Recommendation |
|---|----------|---------|----------------|
| 7a | Exact fields for Volunteer entity | Name only; Name + contact; Name + contact + roles + status | Name + contact phones/emails + active/inactive status + notes minimum |
| 7b | Role model | Roles as columns; Roles as junction table | Junction table preferred (intake, follow-up, foster care, health) — but start simple and evolve |
| 7c | Legacy deduplication strategy | Exact match; Fuzzy match + manual review | Fuzzy match + manual review for production data; automated for clean subsets |
| 7d | Import scope | All legacy volunteers; Only active volunteers | All legacy values imported; inactive marked via status flag |

### Resolution needed

- [x] ~~Confirm whether volunteer references are FK-only~~ → **Decided:** yes, FK-only; free-text assignment is prohibited.
- [x] ~~Confirm whether inactive volunteers can be assigned~~ → **Decided:** no; only active volunteers may be assigned to new records.
- [x] ~~Confirm whether referenced volunteers can be deleted~~ → **Decided:** no; referenced volunteers can only be deactivated, never physically deleted.
- [x] ~~Confirm whether historical records survive deactivation~~ → **Decided:** yes; FK relationships are preserved after deactivation.
- [ ] Confirm exact fields for the Volunteer entity
- [ ] Confirm role taxonomy (intake, follow-up, foster care, health — or different grouping)
- [ ] Confirm whether roles are attributes or junction table
- [ ] Confirm deduplication strategy for legacy free-text values
- [ ] Confirm whether `TbVoluntariosParaAutorrellenables` seed data is usable as a starting point
- [ ] Confirm whether unreferenced volunteers may be deleted (default: deactivation only)

---

## Decision Summary

| # | Decision | Status | Owner | Target |
|---|----------|--------|-------|--------|
| 1 | State derivation formula | Direction decided; schema open | Product / data architect | Feature 01 implementation |
| 2 | Strict mode / date validation | Open | Product owner | Feature 03 implementation |
| 3 | Foster capacity enforcement | Open | Product / operations | Feature 02 implementation |
| 4 | Dynamic report SQL security | Open | Product / security | Feature 04 implementation |
| 5 | ARIAC/RIAC scope | Open | Product / regulatory | Feature 01 implementation |
| 6 | Photo/attachment storage sizing | Open | Infrastructure / product | Infrastructure provisioning |
| 7 | Volunteer Registry (new feature) | Direction decided; business rules clarified; implementation open | Product / data architect | Feature 02 implementation |

## Next step

Each decision must be resolved before the corresponding feature implementation begins. Assign owners and deadlines in the next sprint planning session.
