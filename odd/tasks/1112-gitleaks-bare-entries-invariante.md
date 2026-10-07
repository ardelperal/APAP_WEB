# #1112 — Bare `.gitleaksignore` entries lack an adjacent reason and the documented invariant is stale

## Status

| Field | Value |
|---|---|
| Number | #1112 |
| Type | `type:chore` (`chore(security)`) |
| Priority | (no priority label) |
| Status | `status:approved` |
| Branch | `chore/1112-gitleaks-bare-entries-invariante` |
| Worktree | `apap-app-worktrees/1112-gitleaks-bare-entries-invariante/` |
| Blocked by | (none) |

## Objective

Close the silent drift that the two bare entries in `.gitleaksignore`
introduced: the file has historically pinned every entry to
`<commit>:<file>:<rule>:<line>`, with the stated invariant that a new
secret of the same shape at the same line still fails the gate. The
two bare entries from #1081 (`tests/integration/test_magic_link_state.py:generic-api-key:74`
and `:334`) break that invariant for any future commit that re-introduces
`generic-api-key` on those exact lines — which is a real, narrow
window. The fix has two halves: pin the documented invariant to the
two entry shapes that the runtime actually uses, and harden the
governance test so the next drift fails loud.

## Problem and why

Diagnosis of the three files the issue names:

### `.gitleaksignore` (around lines 110-115)

The block carries one per-fingerprint history entry and two bare
entries with no comment between them and the previous entry:

```
# Commit 01de084620a68d38ee62f6b4d3adf9ff17a793e1 is judgment-day round 1
# of the magic-link state binding; the file itself was deleted from the
# tree in that commit (state now travels in a cookie). Historical-only.
01de084620a68d38ee62f6b4d3adf9ff17a793e1:tests/integration/test_magic_link_state.py:generic-api-key:334
tests/integration/test_magic_link_state.py:generic-api-key:74
tests/integration/test_magic_link_state.py:generic-api-key:334
```

The bare entries are right below the pinned one with no comment of
their own. They have a reason (the test fixture would otherwise re-introduce
the finding on the same line) and a date, but a reader has to
mentally extend the pinned entry's comment to them.

### `tests/test_security_scanning.py:124-146` (`test_gitleaksignore_entries_carry_a_dated_reason`)

The current test checks that *the path of every entry* appears in
*some comment* of the file and that a date appears somewhere. That is
strict enough to pass with the bare entries as they are today, but
not strict enough to fail loud the next time a bare entry is added
without a comment of its own.

### `.github/workflows/ci.yml:592-612` (the documented invariant)

The comment that the workflow exposes to a maintainer reading the
security job says:

> Entries are never path-wide and never value-quoted, so a new secret
> of the same shape still fails the gate.

This invariant is true for the per-fingerprint history entries
(those ARE pinned to a commit) and **false** for the two bare
entries added in #1081. The comment does not name the two entry
shapes the runtime actually accepts, so the next contributor does
not learn from the comment that a bare entry is a deliberate
narrow-window exception, not a default shape.

## Evidencia verificable

- `tests/test_security_scanning.py:124-146` — the governance test that allows the current state.
- `.github/workflows/ci.yml:592-612` — the comment that documents the invariant the bare entries break.
- `.gitleaksignore` lines 113-115 — the two bare entries without an adjacent reason comment.
- `app/modules/contratos/domain/tipos_contrato.py` is *not* affected; this change touches the security allowlist and the workflow comment only.
- Reproducción: `grep -B1 -A1 'generic-api-key' .gitleaksignore` returns the two bare entries without an adjacent reason comment.

## Alcance y no objetivos

### Incluido

- **Harden `tests/test_security_scanning.py`** so every entry in `.gitleaksignore` — both the per-fingerprint history entries and the bare entries — has an **adjacent** comment of the form `YYYY-MM-DD` + a reason, where "adjacent" means the comment is on the line(s) immediately above the entry, separated from the entry by no other entry. The current "path appears in some comment" check is replaced by a check that pins the comment to the specific entry it justifies.
- **Annotate the two existing bare entries in `.gitleaksignore`** with a `2026-10-05 — issue #1109 chain r2` block (or similar) that names the test fixture, the rule, and the narrow window.
- **Update the invariant comment in `ci.yml:592-612`** to name the two entry shapes — `pinned: <commit>:<file>:<rule>:<line>` and `bare: <file>:<rule>:<line>` — and to document the trade-off: bare entries are the *only* rebase-proof shape in `dir` mode (the security job scans with `gitleaks dir .`), and they widen the masking window to any future commit at the same line. The documentation now reflects what the runtime actually does.

### Fuera de alcance

- Restructuring the test fixture `test_magic_link_state.py` to avoid triggering `generic-api-key` (option (c) in the issue body, explicitly excluded).
- Migrating the security job to `gitleaks git` with commit-pinned fingerprints; that would obsolete the bare entries, but it is a separate decision and a separate issue.
- Removing the two bare entries. They are the only rebase-proof way to silence the gate under `gitleaks dir .`; the fix documents and governs them, it does not evict them.

## Criterios de aceptación

- [ ] `tests/test_security_scanning.py` rejects a `.gitleaksignore` whose entries are not adjacent to their reason comment.
- [ ] `tests/test_security_scanning.py` requires the reason comment to carry a `YYYY-MM-DD` date and a non-empty reason line.
- [ ] The two existing bare entries have an adjacent `2026-10-05 — …` reason block.
- [ ] The per-fingerprint history entries still pass the new strict check.
- [ ] `ci.yml:592-612` documents both entry shapes and the trade-off.
- [ ] `make verify` (and specifically the `test_security_scanning` suite) is verde.

## Plan de validación

1. **RED**: add the hardened test that fails against the current `.gitleaksignore` (the two bare entries have no adjacent reason). Run — fails.
2. **GREEN**: add the adjacent reason block to the two bare entries; run — passes.
3. **Update the workflow comment** to name both entry shapes and the trade-off. The hardened test still passes because the trade-off is documentation, not enforcement.
4. **Regression**: verify the existing per-fingerprint history entries still pass the new strict check (they all have adjacent reason blocks).
5. **Final**: `make verify` end-to-end, `mypy`, `ruff`, `pyproject.toml` build.

## Dependencias y riesgos

- **Narrow, accepted window**: the two bare entries mask `generic-api-key` on `test_magic_link_state.py:74` and `:334`. The risk is exactly the same as it was in #1081: a future commit that re-introduces a real `generic-api-key` finding at the same two lines would not fail the gate. The fix does not close that window; it makes it visible and testable.
- **Backward-compat for existing entries**: every per-fingerprint history entry already has an adjacent reason block, so the strict test only blocks new bare entries without a reason — a regression that should fail loud.
- **Documentation drift**: the next contributor who edits the security job in `ci.yml` should see the trade-off spelled out. The updated comment closes that.
- **Not a security boundary change**: this is governance hardening (the test catches future drift) plus documentation. The runtime gate's surface is unchanged; the gate still fails on the same set of inputs.

## Decisión de producto pendiente (§3 ODD)

None — the body of #1112 already names the two halves (workflow comment + governance test) and the trade-off is documented inside the issue. The fix follows the issue's acceptance criteria verbatim.
