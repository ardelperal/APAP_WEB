# Delta for migration-discovery-docs

## ADDED Requirements

### Requirement: Source Snapshot Identity in Discovery

The discovery documentation SHALL define a `source-snapshot-identity` section under `migration-risks.md` that mandates SHA-256 of the `.accdb` file and SHA-256 of the photos directory be computed and persisted in `migration.lock_snapshot.json` before any legacy read. The section MUST specify: hash algorithm, what files are hashed, where the snapshot file lives, what fields it carries (`accdb_sha256`, `photos_dir_sha256`, `last_apply_at`, `last_apply_direction`), and that snapshot drift between consecutive apply runs is informational (logged via `log_safe` with hash prefixes, no raw paths) and not blocking.

(Previously: Discovery docs did not define source-snapshot identity; drift between apply runs was undetectable.)

#### Scenario: Snapshot identity section documents the contract

- GIVEN `migration-risks.md` exists
- WHEN the source-snapshot-identity section is read
- THEN it states SHA-256 of `.accdb` + SHA-256 of photos dir
- AND it states the snapshot file path `migration.lock_snapshot.json`
- AND it lists the four required fields with types

#### Scenario: Drift handling documented

- GIVEN the source-snapshot-identity section
- WHEN a reviewer checks the drift policy
- THEN the policy states drift is informational and logged via `log_safe` with hash prefixes
- AND raw filesystem paths MUST NOT appear in logs

#### Scenario: Empty source is a valid snapshot

- GIVEN the section's empty-source paragraph
- WHEN a fresh `.accdb` with 0 rows in `animales` runs apply
- THEN the snapshot is written with empty-table hashes
- AND `applied=0`, `skipped=0`, `errors=[]`

### Requirement: Collision Policy in Discovery (Web-Only and Reverse-Path Scope)

The discovery documentation SHALL define a `collision-policy` section that documents the policy for web-side UNIQUE constraint collisions on `voluntarios.DNI`. The section MUST state: (a) `TbVoluntariosParaAutorrellenables` does NOT have a `DNI` column (verified by Dysflow `get_schema`); (b) `voluntarios.dni` is web-only with `web_only_strategy: preserve`; (c) web DOES enforce UNIQUE on `voluntarios.dni`; (d) forward legacy→web apply never produces a DNI collision (legacy has no DNI); (e) collisions are possible in two scopes: web-only manual inserts (multiple web rows with same DNI) and reverse-path (web→legacy) when web tries to push a DNI back to legacy (no column); (f) first INSERT wins in both scopes; (g) subsequent collisions are routed to `web_only_feature_shadow` with `reconciliation_status="needs_review"` and `review_reasons=["dni_collision"]`; (h) the policy is deterministic by `legacy_pk` (forward) or `web_pk` order (reverse); (i) reconciliation is operator-in-the-loop via `apap-migrate reconcile --interactive` per `web-only-feature-preservation` REQ-005.

(Previously: Discovery docs assumed `DNI` exists in legacy; this is corrected to reflect the verified schema reality. Forward-apply collisions for `DNI` are impossible by construction.)

#### Scenario: Collision policy section enumerates the rules

- GIVEN `collision-policy.md` or equivalent section exists
- WHEN read
- THEN it lists all nine rules above
- AND it cross-references `web-only-feature-preservation` REQ-005
- AND it cites the Dysflow `get_schema` evidence for the "no DNI in legacy" claim

#### Scenario: Operator-in-the-loop reconciliation documented

- GIVEN the collision-policy section
- WHEN a reviewer traces the operator workflow
- THEN the doc points to `apap-migrate reconcile --interactive`
- AND it states `keep web` / `accept derived` / `defer` are the three resolutions
- AND it notes that for `DNI`, `accept derived` is rarely meaningful (legacy has no DNI to derive FROM)

### Requirement: Privacy Evidence Contract in Discovery

The discovery documentation SHALL define a `privacy-evidence` section that mandates count + hash evidence (not raw PII) in all migration reports, CLI output, and audit documents. The section MUST enumerate the PII columns: `Email`, `Tel1`, `Tel2` (legacy-present, migrated 1:1) AND `DNI` (web-only, `web_only_strategy: preserve`, NOT in legacy per Dysflow `get_schema`); the 15-field `log_safe` redaction list (12 existing + `dni, tel1, tel2`); and the privacy invariants tests must prove.

(Previously: Discovery docs enumerated `DNI` as legacy-present; this is corrected to reflect the verified schema. The redaction list grows from 12 to 15 fields.)

#### Scenario: PII column enumeration

- GIVEN the privacy-evidence section
- WHEN read
- THEN it lists `Email`, `Tel1`, `Tel2` as PII present in legacy (`TbVoluntariosParaAutorrellenables`) and migrated 1:1
- AND it lists `DNI` as PII web-only with `web_only_strategy: preserve`, NOT in legacy
- AND it cites Dysflow `get_schema` evidence for the column inventory

#### Scenario: log_safe redaction contract documented

- GIVEN the section
- WHEN read
- THEN it states that `log_safe` payloads MUST NOT contain raw PII values
- AND it enumerates the 15-field redaction list (12 existing from `app/core/logging.py:41` + `dni, tel1, tel2` added in PR4)
- AND it specifies which field maps to which column (`dni` field redacts `DNI` value, `tel1` field redacts `Tel1` value, `tel2` field redacts `Tel2` value)

## Out of Scope (delta)

- Choice of driver for the legacy executor (pyodbc vs. snapshot adapter) — design selects with a TDD spike.
- Specific page-level UI for collision resolution — CLI only per `web-only-feature-preservation`.
- Any change to the Access/.accdb schema or destructive cleanup.
