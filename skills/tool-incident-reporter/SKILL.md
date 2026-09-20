---
name: tool-incident-reporter
description: Trigger: tool gap, dysflow friction, codegraph-vba friction, maintainer escalation, upstream issue. Detects friction in a tool the consumer uses (especially Dysflow/CodeGraph-VBA) and files a single GitHub issue per independent problem at the tool's upstream repo, with a TDD-disciplined maintainer prompt as the body. Uses issue-creation mechanics for the remote side; preserves working behavior and no-touch rules. Reporter does NOT repair, release, or align.
license: Apache-2.0
metadata:
  author: ardelperal
  version: 0.1
  last_verified: 2026-09-16
  scope: ['universal']
  auto_invoke: ['detecting tool friction', 'drafting a maintainer prompt', 'filing an upstream tool issue']
  tiers: ['universal']
---

# Tool Incident Reporter

> **Consolidation.** This skill is the result of merging `vba-toolkit-evolve` (detect + file) and `maintainer-prompt-drafter` (prompt structure) per Engram #27852. Source skills are kept as redirects for backward reference; load THIS skill for new tool-incident work.

Detects friction in a tool the consumer uses and files ONE GitHub issue per independent problem at the tool's upstream repo. The issue body is a TDD-disciplined maintainer prompt with reproducibility evidence, what-works guardrails, and acceptance outputs. Activation is conditional on tool use — not VBA-only, not automatic for all consumers.

## When to load

- The consumer detects a bug or gap in a tool it uses (MCP, CLI, library, framework — primarily `DysTelefonica/dysflow` and `ardelperal/codegraph-vba`).
- A workaround appears mid-session for a tool behavior the consumer didn't expect.
- The user explicitly names this skill.

**Do NOT load** for: changes inside a single project (use `sdd-apply`), changes in a single non-tool skill (use `skill-improver`), post-fix verification of a tool change (use `maintainer-prompt-drafter`'s pre-existing prompt archive as a record; this skill doesn't re-verify), or post-release re-alignment of consumer skills (use `dysflow-codegraph-update`).

## Hard Rules

- **Per-incident, not per-session.** Each independent problem = one issue. Accumulating multiple frictions in a single issue dilutes triage. If a session finds two independent frictions, file two separate issues.
- **Capture the runtime version explicitly.** Every issue body must include the actual version of the tool observed (not a range, not "latest"). The maintainer reproduces against that exact build.
- **Distinguish facts from hypotheses, and tool from consumer/environment.** Mark every observation with one of: `observed` (reproduced), `reported` (user-stated, not yet reproduced), `hypothesis` (suspected cause). Mark the failure locus as `tool` (defect in the tool), `consumer` (defect in how the consumer used it), or `environment` (OS, network, config). Never mix.
- **Reproducibility evidence is mandatory.** Paste literal logs/commands/output, not summaries. Include: operation attempted, expected vs observed, minimal sanitized repro (no secrets), workaround used, continuity of previous attempts.
- **What-works guardrails are mandatory.** List the working behavior the fix MUST NOT break. No-touch limits: what the maintainer must not change, what files/configs/contracts are off-limits. Without these the maintainer breaks things.
- **Reuse `issue-creation` mechanics for the remote side.** Target repo resolution, target forms (label, milestone, assignees), permissions, privacy scrub, readback of URL. Do NOT duplicate that mechanics here.
- **One attempt, then readback or admit uncertainty.** Authorized create OR equivalent comment; on failure, report the URL of the failed attempt OR state the uncertainty explicitly. NO blind retries.
- **No default `status:approved`, no session grouping, no prescribed fix strategy.** No branch suggestion (suggest `fix/<gap-summary>` convention only), no version bump prescription, no TDD imposition on the maintainer, no invented RED results.
- **Reporter does NOT repair, release, or align.** No commits/PRs to the tool repo, no releases, no post-fix alignment. The maintainer owns the fix; this skill only reports.
- **Issue is the main deliverable.** Local archive (`docs/prompts/prompt-ia-mantenedora-<tool>-<round>-<YYYY-MM-DD>.md`) is optional and only if the consumer repo is collaborative. Default: issue only.
- **One problem per issue.** Do not aggregate unrelated frictions even if observed in the same session. Cross-references are fine; merging bodies is not.
- **No secrets inline.** Passwords, tokens, customer data — sanitize or omit. Use env vars or placeholders.

## Decision Gates

| Situation | Action |
|---|---|
| Consumer detected a tool bug mid-session | File one issue per independent friction. Capture: runtime version, repro, expected/observed, workaround, what-works, no-touch limits. |
| User names this skill explicitly with context | Produce the issue body and file via `issue-creation`. |
| User says "ya está", "acabó", "aplica tu protocolo" | **NOT** this skill. That's post-fix verification (use `maintainer-prompt-drafter` as archive). |
| Multiple unrelated frictions in same session | File separately. Reference prior issues in body if relevant. |
| Same friction observed across multiple sessions (round > 1) | Search engram for prior round; reference it; do NOT re-state already-fixed gaps. Preserve scope continuity. |
| Cannot reproduce but user reported symptom | Mark `reported` not `observed`; capture what the user gave; do not invent a repro. |
| Tool repo is private or behind auth | Stop. Authorize or report the access boundary; do not assume. |

## Execution Steps

1. **Triage.** Determine whether the observed symptom is `tool`, `consumer`, or `environment`. If `consumer` or `environment`, fix locally or redirect; do not file an upstream issue.
2. **Capture.** Collect: runtime version, operation attempted, expected vs observed, minimal sanitized repro, workaround used, prior attempt continuity (search engram for `<tool-name> round <N>`), what-works, no-touch limits.
3. **Mark each fact.** Tag every line in the body: `observed` / `reported` / `hypothesis` for evidence; `tool` / `consumer` / `environment` for locus. The maintainer uses these to prioritize and to avoid blaming the wrong component.
4. **Resolve target.** Use `issue-creation` to identify the upstream repo (`DysTelefonica/dysflow`, `ardelperal/codegraph-vba`, or other tool declared at trigger time), the exact target form (label, milestone, assignees), permissions, and privacy scrub.
5. **Compose the body.** Use the maintainer-prompt template: situation, what-works, gap, repro, evidence, no-touch limits, acceptance output (PR / changelog / version bump — *suggested*, not prescribed). Avoid "I think", "maybe", "probably".
6. **File.** Authorized create OR equivalent comment. One attempt. Readback the URL or admit uncertainty. NO blind retries.
7. **Report to user.** Inline summary: issue number, friction reported, target repo, next step expected from the maintainer. Do not auto-trigger anything else.

## Output Contract

```json
{
  "status": "filed|blocked|skipped",
  "tool": "<tool-name>",
  "tool_version": "<exact observed version>",
  "target_repo": "<owner>/<repo>",
  "issue_number": <n>,
  "issue_url": "<url>",
  "friction_class": "tool|consumer|environment",
  "evidence_class": "observed|reported|hypothesis",
  "what_works_preserved": ["<list of working behaviors not to break>"],
  "no_touch_limits": ["<list of off-limits files/configs/contracts>"],
  "reproduction_evidence_present": true,
  "readback": "ok|uncertain",
  "local_archive_path": "docs/prompts/prompt-ia-mantenedora-<tool>-<round>-<YYYY-MM-DD>.md or null",
  "next_recommended": "wait_maintainer|none"
}
```

## Anti-patterns

- Filing an issue without the runtime version — maintainer cannot reproduce.
- Aggregating multiple frictions in one issue — dilutes triage and acceptance.
- Inventing a minimal repro when the symptom wasn't reproduced — mark `reported` instead.
- Auto-applying `status:approved` or any label the consumer doesn't actually have permission for.
- Suggesting a specific branch name, version bump, or release date — that's the maintainer's call.
- Repairing the tool repo, opening a PR, running a release — out of scope; reporter only.
- Polling the issue status, retrying the create, or auto-generating a follow-up comment.
- Re-stating gaps already covered in a prior round — reference them, don't duplicate.
- Including secrets, customer data, or unredacted log lines.

## References

- `issue-creation` skill — remote mechanics: target repo, permissions, labels, privacy, readback. Reused here for the GitHub side.
- `maintainer-prompt-drafter` skill — historical source for the maintainer-prompt structure (modes, variants, 7-step flow). Kept for backward reference; this skill supersedes it for new tool-incident work.
- `vba-toolkit-evolve` skill — historical source for the detect + file loop. Kept for backward reference; this skill supersedes it.
- `dysflow-codegraph-update` — post-release alignment of consumer skills. NOT invoked from here; maintainer invokes it after the fix.
- `skills/skill-style-guide/SKILL.md` — structure, frontmatter, body budget for new skills.
