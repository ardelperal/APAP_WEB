---
name: vba-run-tests
description: Trigger: run VBA tests, validate a VBA manifest, execute an Access regression subset, diagnose Access test cleanup. Executes manifest-driven VBA tests with compilation, authorization, and process-ownership gates.
license: Apache-2.0
metadata:
  author: Andrés Román
  version: 3.0.0
  last_verified: 2026-08-28
  scope: ['vba', 'runtime']
  auto_invoke: ['running VBA tests via dysflow']
  tiers: ['vba', 'runtime']
---



## §1 Activation

Load before running a VBA test manifest or focused test subset through Dysflow. Load `dysflow-usage` first; use runtime discovery for current parameters and error envelopes.

## §2 Hard Rules

- **HR-1** — Call bootstrap and the tests schema index before selecting test tools.
- **HR-2** — Resolve the exact worktree, frontend binary, and sandbox target before execution.
- **HR-3** — Validate the manifest before every manifest-driven `test_vba` call.
- **HR-4** — Block execution when manifest validation fails.
- **HR-5** — Check `humanCompilePending` before `test_vba` and require `false`.
- **HR-6** — Stop and request human compilation when `humanCompilePending` is `true`.
- **HR-7** — Re-check `humanCompilePending` after human confirmation and before test execution.
- **HR-8** — Read authorization explicitly with `get_capabilities({view:"compact", include:["allowedProcedures"]})` before execution.
- **HR-9** — Treat a missing or empty `allowedProcedures` list as unrestricted and only a non-empty list as restrictive.
- **HR-10** — Record an out-of-list procedure as blocked; never auto-add it, because a human or configuration owner decides authorization.
- **HR-11** — Run tests only against sandbox or isolated test data, never production.
- **HR-12** — Inspect owned Access operations before and after the run.
- **HR-13** — Clean only Dysflow-owned operations through ownership-safe runtime tools.
- **HR-14** — Never terminate unrelated Access processes or infer process ownership from names alone.

## §3 Decision Gates

| Condition | Action |
|---|---|
| Manifest is provided | Run `validate_manifest`; continue only when valid. |
| Manifest validation fails | Return typed errors and do not call `test_vba`. |
| `humanCompilePending:true` | Stop, ask the human to compile in Access, then re-check before `test_vba`. |
| `humanCompilePending:false` | Continue to authorization and execution gates. |
| `allowedProcedures` is missing or empty | Continue; execution is unrestricted by procedure authorization. |
| `allowedProcedures` is non-empty and contains every selected procedure | Continue to execution. |
| A selected procedure is outside a non-empty list | Return `status: "blocked"`; the human or configuration owner decides whether to change configuration. |
| Target resolves to production or an unverified backend | Block execution without touching data. |
| A pre-existing Access process is not owned by this run | Leave it untouched and report the lock/blocker. |
| This run leaves a Dysflow-owned operation | Use ownership-safe cleanup and report the result. |

## §4 Execution Steps

1. Call `bootstrap({phase:"tests"})`, `schema({view:"index", phase:"tests"})`, and selective `describe_tool` for `validate_manifest` and `test_vba`.
2. Resolve the project and verify the binary, sandbox, and write gates; fetch `allowedProcedures` through `get_capabilities({view:"compact", include:["allowedProcedures"]})`.
3. List Access operations and record only evidence returned by Dysflow.
4. Run `validate_manifest` for the selected manifest; stop on any invalid result.
5. Read `humanCompilePending`; when true, stop for human compilation and re-read it after confirmation.
6. Apply authorization only when `allowedProcedures` is non-empty; block out-of-list procedures without editing configuration.
7. Call `test_vba` only after manifest, compilation, authorization, and sandbox gates pass.
8. List Access operations again and clean only operations proven to belong to this run.
9. Return every Output Contract key, including empty arrays and null values.

## §5 Output Contract

| Key | Type | Description |
|---|---|---|
| `status` | `"success" \| "blocked" \| "failed"` | Overall test-run outcome. |
| `manifest_path` | `string \| null` | Validated manifest, or null for a supported inline subset. |
| `manifest_valid` | `boolean` | Manifest validation result. |
| `manifest_errors` | `object[]` | Typed validation errors; empty when none. |
| `human_compile_pending` | `boolean` | Last observed compilation gate. |
| `authorization_blockers` | `string[]` | Unauthorized procedures or configuration blockers. |
| `tests_run` | `object[]` | Per-test structured results; empty when none ran. |
| `summary` | `object` | Aggregate counts and duration; present even when blocked. |
| `owned_operations_cleaned` | `string[]` | Owned operation identifiers cleaned after the run. |
| `unrelated_processes_touched` | `boolean` | Must remain false. |
| `blocked_reasons` | `string[]` | Blocking reasons; empty on success. |
| `next_recommended` | `string` | Next action, or `"none"`. |
| `risks` | `string[]` | Remaining risks; empty when none. |

## Anti-patterns

| Symptom | Fix |
|---|---|
| `test_vba` runs before manifest validation | Validate first and stop on typed errors. |
| Test execution starts while human compilation is pending | Stop, obtain human confirmation, and re-check the gate. |
| An unauthorized procedure causes an automatic allowlist edit | Report the blocker and require an explicit configuration decision. |
| All Access processes are terminated to clear one lock | Use operation ownership evidence and clean only Dysflow-owned operations. |
