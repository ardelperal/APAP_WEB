# Review Authority Inventory Recovery Runbook (issue #198)

Covers diagnosis and recovery of the `gentle-ai review` authority inventory when
entries are stuck in non-terminal states or the inventory reports
`authoritative: false / complete: false / status: invalid`.

## Background

APAP_WEB runs in **pre-MVP single-branch mode** (`rdd_mode: off` globally).
The pre-MVP merge gate is **CI** (per user directive, 2026-07-18: "no reviewers
in pipeline"). The `gentle-ai review` CLI maintains a compact-v2 authority
inventory in the shared Git common directory (`.git/gentle-ai/review-transactions/`).

Inventory state lives in the **`00_main` worktree's git store** — all worktrees
share the same `.git` via `git worktree`. Operations from any worktree mutate the
same inventory.

---

## When to Trigger

Run this runbook when:

- `gentle-ai review status --cwd .` returns `authoritative: false` or
  `status: invalid`.
- `gentle-ai review validate --gate <gate> --cwd .` returns
  `result: invalidated, reason: "complete review authority inventory is unavailable
  or corrupted"`.
- Entries appear with `state: reviewing` or `state: correction_required` that
  never progress and block `status: complete`.

---

## Pre-Flight Diagnosis

```powershell
# 1. Check overall inventory health
gentle-ai review status --cwd .

# 2. Check RDD mode (must be "off" in pre-MVP)
gentle-ai review mode status --cwd .

# 3. Check for entry-level diagnostics
gentle-ai review inspect-authority --cwd .

# 4. Try repair preflight
gentle-ai review repair --preflight --cwd .
```

Expected pre-MVP state:
- `authoritative: true, complete: true, status: active` (acceptable;
  `status: complete` requires all entries in terminal states — see Known
  Limitations below).
- `repair --preflight` → `status: unsupported, eligible_candidates: 0`.

---

## Cleanup Recipe for Stuck `reviewing` Entries

Entries in `state: reviewing` with no captured lens results are **pristine** and
can be abandoned. An abandoned entry moves to quarantine; the inventory entry count
decreases.

### Identify Reviewing Entries

```powershell
$status = gentle-ai review status --cwd . | ConvertFrom-Json
$status.entries | Where-Object { $_.state -eq 'reviewing' } |
  Select-Object lineage_id, revision, snapshot_identity
```

### Abandon Each Entry

Authorization template (6-line LF-only, no trailing newline):

```
gentle-ai.review-abandon-authorization/v1
lineage=<lineage_id>
revision=<revision>
snapshot_identity=<snapshot_identity>
actor=<actor>
reason=<reason>
```

Example PowerShell helper:

```powershell
function Abandon-ReviewingEntry {
    param([object]$Entry, [string]$Reason, [string]$Actor, [string]$Cwd)
    $auth = @"
gentle-ai.review-abandon-authorization/v1
lineage=$($Entry.lineage_id)
revision=$($Entry.revision)
snapshot_identity=$($Entry.snapshot_identity)
actor=$Actor
reason=$Reason
"@
    $authFile = "$env:TEMP\auth_$($Entry.lineage_id).txt"
    $auth | Out-File -FilePath $authFile -Encoding UTF8 -NoNewline
    gentle-ai review abandon `
        --lineage $Entry.lineage_id `
        --expected-revision $Entry.revision `
        --actor $Actor `
        --reason $Reason `
        --maintainer-authorization (Get-Content $authFile -Raw) `
        --cwd $Cwd
    Remove-Item $authFile
}
```

---

## Legacy-v1 Entry Handling

Legacy-v1 entries (`issue-*-*` lineage IDs) with `status: historical-pre-receipt`
are already in a semi-terminal state. They do **not** block `status: complete`.

If they show `status: invalid` with diagnostic "terminal legacy authority is
missing its receipt", use `quarantine-legacy` with the exact diagnostic:

```powershell
gentle-ai review quarantine-legacy `
    --lineage "<lineage_id>" `
    --expected-revision "<revision>" `
    --diagnostic "terminal legacy authority is missing its receipt" `
    --disposition historical-pre-receipt `
    --actor andres `
    --reason "issue-198" `
    --maintainer-authorization "gentle-ai.review-legacy-quarantine-authorization/v1
lineage=<lineage_id>
revision=<revision>
diagnostic=terminal legacy authority is missing its receipt
disposition=historical-pre-receipt
actor=andres
reason=issue-198"
```

Note: `quarantine-legacy` only accepts the diagnostic
`malformed historical findings-freeze`. For entries already in
`historical-pre-receipt` state, no further action is needed.

---

## Validate After Cleanup

```powershell
# For a worktree without remote tracking, provide --base-ref explicitly:
gentle-ai review validate --gate pre-push --base-ref origin/main --cwd .

# Expected in pre-MVP (empty publication range — nothing to push):
# { "result": "allow", "allowed": true, "reason": "the publication range is empty" }

# If the branch has commits ahead of origin/main:
gentle-ai review validate --gate pre-push --base-ref origin/main --cwd .
```

In pre-MVP, `validate` returns `result: invalidated` with reason
`"review-driven development is disabled and no receipt governs this candidate"`
when no `--base-ref` is provided and the worktree has no remote tracking. This is
**expected behaviour** — the pre-MVP gate is CI, not review receipts.

---

## Known Limitations

### `status: active` instead of `status: complete`

The inventory may show `authoritative: true, complete: true, status: active`
even after cleanup. `status: complete` requires **all entries** to be in terminal
states (`approved`, `invalidated`, `superseded`, `quarantined`). Three entry
shapes currently have **no resolution path in pre-MVP** because they require
reviewer participation:

| Shape | Count | Blocker |
|---|---|---|
| `active/correction_required` | 1 | `reopen-results` fails: "reviewer artifact is unreadable or outside the native size bound" — the preserved lens result artifact is corrupted/missing. No CLI command quarantines this shape today. |
| `active/validating` | 2 | Same corrupted-artifact issue; `reopen-results --prepare` fails identically. |

These entries cannot be abandoned (they are not pristine) and cannot be disposed
(no usable lens result to dispose). They remain as known limitations until:

1. The gentle-ai CLI ships a command to force-quarantine entries with corrupted
   artifacts, **or**
2. A reviewer re-runs the review end-to-end, producing fresh artifacts.

**Pre-MVP workaround**: treat `status: active` with `authoritative: true,
complete: true` as the acceptable clean state. CI gates remain operative.

---

## Rollback

Abandon operations are **terminal and idempotent** — re-running abandon on an
already-quarantined entry converges without error. There is no rollback for a
committed abandon; the entry stays in quarantine.

To inspect quarantine:

```powershell
# Quarantine paths are under the shared .git directory:
# .git/gentle-ai/review-transactions/quarantine/<lineage_id>-<timestamp>/
```

---

## Related

- `gentle-ai review mode` — enable/disable RDD; `off` is correct for pre-MVP.
- `gentle-ai review repair --preflight` — classify inventory health.
- `gentle-ai review inspect-authority` — deep inventory inspection.
- `docs/audits/review-authority-inventory-cleanup-2026-Q3.md` — audit doc.
- Issue #198: <https://github.com/ardelperal/APAP_WEB/issues/198>
