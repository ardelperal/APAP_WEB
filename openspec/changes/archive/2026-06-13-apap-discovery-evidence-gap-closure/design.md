# Design: APAP Discovery Evidence Gap Closure

## Technical Approach

Documentation-only follow-up. Execute Dysflow read-only tools against the live Access backend to validate six evidence source gaps, then update the relevant `docs/discovery/` markdown files with confirmed findings. No code changes, no database writes.

## Architecture Decisions

### Decision: Dysflow-only validation

**Choice**: Use Dysflow MCP tools exclusively for all schema/query validation
**Alternatives considered**: Direct SQL client, VBA export scripts
**Rationale**: User specified APAP runtime is Dysflow only; read-only tools are safe and auditable

### Decision: Single-commit documentation update

**Choice**: All doc updates in one commit
**Alternatives considered**: Per-gap commits
**Rationale**: All changes are documentation corrections to the same set of files; individual commits add review overhead without value

## Data Flow

```
Dysflow MCP (read-only) ──→ Evidence findings ──→ docs/discovery/ updates
       │                                                │
       └── get_schema, query_sql, get_relationships     └── acceptance-checklist.md
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `docs/discovery/data-model-completeness.md` | Modify | Update TbAuxAnimales schema, catalog domain values, FK enforcement evidence blocks |
| `docs/discovery/feature-02-intake-foster-adoption.md` | Modify | Update foster capacity query evidence source |
| `docs/discovery/feature-03-health-care.md` | Modify | Update date validation and puppy-test evidence sources |
| `docs/discovery/acceptance-checklist.md` | Modify | Fill verification summary pass/fail columns |

## Interfaces / Contracts

No new interfaces. All changes are markdown content updates within existing evidence source block format:

```markdown
#### Evidence Source

- **Table:** {table names}
- **Dysflow tool:** {tool used}
- **Query:** {actual SQL executed}
- **Result:** {finding summary}
- **Verified:** [x]
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Doc consistency | Cross-references between updated docs | Manual review of link targets |
| Evidence accuracy | Query results match documented rules | Compare Dysflow output against doc claims |
| Checklist completeness | All 44 criteria have pass/fail/not-assessed | Count and sum verification |

## Migration / Rollout

No migration required. Documentation-only change committed to `docs/discovery/`.

## Open Questions

None — all gaps are well-defined from the previous change's verify report.
