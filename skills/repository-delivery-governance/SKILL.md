---
name: repository-delivery-governance
description: Trigger: CI/CD audit, pipeline quality, issue policy, PR policy, labels, branch protection, merge permissions, deployment governance. Audit and harden a repository's path from issue intake to production.
license: Apache-2.0
metadata:
  author: ardelperal
  version: "1.1"
  last_verified: 2026-09-13
  scope: ['universal', 'ops']
  auto_invoke: ['auditing repository delivery governance', 'bootstrapping issue and pull request templates', 'configuring branch protection or deployment policy']
  tiers: ['universal', 'ops']
---

## §1 Activation Contract

Load this skill when the user asks to audit, design, document, or harden any
part of a repository's delivery system:

- issue intake, approval states, ownership, or duplicate handling;
- pull or merge request policy, labels, review size, or required evidence;
- branch protection, rulesets, merge roles, bypasses, or direct-push policy;
- CI quality gates, permissions, dependency integrity, or test orchestration;
- artifact publication, deployment, smoke checks, promotion, or rollback;
- drift between documented policy, workflow code, and live host configuration.

Use it for any repository or CI provider. Discover the target's vocabulary and
capabilities before applying GitHub-, GitLab-, or platform-specific mechanics.

Do not use it as a replacement for a target repository's implementation,
testing, security, issue-creation, or PR-creation skills. Load those companions
when the task crosses their scope.

## §2 Hard Rules

- **HR-1 — Resolve the target.** Identify the repository root, default branch,
  hosting service, CI provider, deployment target, and current policy sources
  before judging quality.
- **HR-2 — Establish authority.** Treat inspection as read-only and require
  explicit authorization for every remote mutation, credentialed session, and
  destination. Never probe a write to discover permissions.
- **HR-3 — Read before inferring.** Inspect repository instructions,
  contribution docs, issue and PR templates, workflow definitions, ownership
  files, release docs, and deployment runbooks before proposing changes.
- **HR-4 — Separate policy from enforcement.** Classify every rule as
  documented, locally validated, CI-enforced, host-enforced, or manual. Never
  describe a convention as a gate without executable evidence.
- **HR-5 — Verify live claims.** Treat branch protection, rulesets, required
  checks, repository visibility, roles, environments, and secrets as unstable.
  Read them from the target host before relying on them.
- **HR-6 — Preserve least privilege.** Grant workflows and people only the
  permissions required for their lane. Contributor access must not silently
  imply approval, protected-label, merge, deployment, or administration rights.
- **HR-7 — Protect the default branch.** Require reviewable change integration,
  block force pushes and deletion, and define who may update the branch. Never
  use administrator bypass to compensate for red or missing required checks.
- **HR-8 — Keep intake traceable.** Define how duplicate search, issue type,
  approval, claim, acceptance criteria, and closing references connect work to
  a pull request. Do not require labels that contributors cannot apply without
  documenting the authorized handoff.
- **HR-9 — Make PR evidence honest.** Require the actual commands, outcomes,
  skips, known failures, risk, rollback scope, and linked issue. Do not accept
  checkboxes that contradict repository or host state.
- **HR-10 — Budget reviewer load.** Define a measurable review-size rule or an
  equivalent complexity budget, plus a documented exception authority and
  evidence requirement.
- **HR-11 — Make CI deterministic.** Pin third-party actions or images by
  immutable identity, lock dependencies, constrain caches, cancel superseded
  runs safely, and ensure required checks have stable names.
- **HR-12 — Isolate trust boundaries.** Prevent untrusted change contexts from
  receiving deployment credentials, write tokens, protected environments, or
  reusable-workflow privileges they do not need.
- **HR-13 — Aggregate without hiding.** Use a stable required gate when matrix
  or conditional jobs vary, but make it fail closed when any required upstream
  job is failed, cancelled, missing, or unexpectedly skipped.
- **HR-14 — Separate validation from deployment.** Prove the proposed revision
  before merge, then deploy only an immutable revision whose evidence can be
  traced back to that green validation.
- **HR-15 — Verify delivery.** Scan and smoke-test the published artifact,
  verify the deployed revision, and provide an executable rollback path. A
  successful webhook or upload is not deployment proof.
- **HR-16 — Preserve evidence.** Record workflow run, source revision, artifact
  digest, environment, deployment result, and rollback result without exposing
  secrets or personal data.
- **HR-17 — Keep docs synchronized.** Update contributor and operator docs in
  the same change as enforcement. When documentation and executable behavior
  disagree, report the executable behavior and repair the documentation.
- **HR-18 — Verify after mutation.** Read back every changed workflow, policy,
  label, ruleset, protection, environment, and deployment state from its
  authoritative surface before declaring success.
- **HR-19 — Preserve repository templates.** Treat existing issue forms and pull
  request templates as authoritative. Bootstrap an asset from this skill only
  when the corresponding repository template is missing and the user explicitly
  authorizes that file change.
- **HR-20 — Adapt portable assets.** Discover the target's existing label
  taxonomy and hosting capabilities before copying an asset. Replace unsupported
  labels, fields, closing syntax, or host-specific paths rather than creating a
  contradictory parallel convention.
- **HR-21 — Solve required-check aggregation across files, not just within
  one.** When required checks span multiple CI workflow files and the
  provider's native job-dependency mechanism cannot cross files (GitHub
  Actions `needs:` is scoped to one workflow file), invoke the other
  workflows as callable/reusable jobs from the aggregator's own workflow so
  one deterministic gate can depend on all of them. Never settle for a
  host-side list of independently named required checks that can silently go
  stale when a job is renamed, moved, or removed.
- **HR-22 — Gate expensive test suites on the release path, not only on a
  calendar.** When mutation testing, deep security scans, or end-to-end
  suites are too slow or noisy to run on every push, wire them to run at
  minimum on the release-cut trigger (tag push, publish workflow) in
  addition to any schedule or manual dispatch. A suite that only runs on a
  weekly cron with no release-time enforcement lets regressions ship for
  days before anything catches them.
- **HR-23 — Deny self-hosted runners to untrusted trigger contexts by
  construction.** Lint every job's `runs-on` against its `if:` condition; a
  job reachable by `pull_request` or any other externally triggered event
  MUST declare a literal hosted-runner label, never a self-hosted label,
  unless its `if` statically excludes that event. A misconfigured job is a
  privilege-escalation path from untrusted PR code onto the self-hosted
  host.
- **HR-24 — Sign and verify published artifacts, not only scan them.** When
  an artifact is published to a registry, sign it with a verifiable,
  keyless mechanism (e.g. Sigstore/Cosign with OIDC) immediately after
  publish, and verify that signature and its certificate identity before
  any deployment or promotion step trusts the digest. A vulnerability scan
  proves the artifact was clean at scan time, not that the digest reaching
  deployment is the one that was scanned.

## §3 Decision Gates

| Condition | Action |
|---|---|
| The request is an audit or explanation | Inspect and report only; do not mutate files or remote state. |
| The user authorizes repository-file changes but not remote changes | Change workflows/docs locally; report live configuration as pending. |
| Remote destination, operation, or credentialed session is ambiguous | Stop remote work and request the single missing authorization fact. |
| The target has a repository-specific delivery skill | Load it and let the stricter target rule override this portable baseline. |
| A rule exists only in documentation | Mark it `documented-only`; propose an executable or manual owner. |
| A gate exists only in CI | Add human-facing recovery instructions or document why none are needed. |
| The host cannot enforce the desired rule for the current plan or visibility | Report the capability gap; compare upgrade, visibility, bot, or manual-control tradeoffs. |
| The repository has one maintainer | Permit zero required second-party approvals only when required CI and merge-role boundaries remain enforced. |
| Multiple maintainers can merge | Require an explicit review policy proportional to risk and ownership. |
| A contributor cannot apply a required label | Define a maintainer or automation handoff; never tell the contributor to retry unauthorized writes. |
| A PR exceeds the review budget | Split it, or require a named exception authority and written rationale. |
| A required job is legitimately inapplicable | Encode and test the skip contract; the aggregate gate must distinguish expected from unexpected skips. |
| Required checks span more than one CI workflow file and native job dependency can't cross files | Wrap the other workflows as callable/reusable jobs from the aggregator's workflow so one gate depends on all of them. |
| A slow suite (mutation, deep security scan, e2e) is scheduled but not wired to the release trigger | Add the release/tag-push trigger to that job, or require a recent green run before publish. |
| Fork or external code runs | Use read-only tokens and no secrets; move privileged work to a trusted post-merge or approval-bound lane. |
| The repository publishes an artifact | Prefer build-once immutable promotion over rebuilding independently per environment. |
| The repository does not deploy | Mark deployment controls `not_applicable`; do not invent a deployment lane. |
| Deployment cannot verify its revision | Treat the release as unverified and block success claims. |
| Existing behavior and docs disagree | Treat executable evidence as current fact, then update docs in the authorized change. |
| A repository already has the corresponding issue or PR template | Keep it authoritative; audit or adapt it instead of copying this skill's asset over it. |
| A required issue or PR template is missing and local file creation is explicitly authorized | Bootstrap the matching asset, then adapt its labels and syntax to the target host. |
| An asset names a label or feature unavailable on the target host | Map it to the repository's verified equivalent or report the capability gap; do not invent support. |

## §4 Execution Steps

1. **Resolve scope.** Establish the repository root and whether the user wants
   audit, design, documentation, implementation, live configuration, or the
   complete lifecycle.
2. **Load local contracts.** Read the target's agent instructions and matching
   skills. Inspect `CONTRIBUTING`, security policy, code owners, issue forms,
   PR template, workflow files, dependency update configuration, release docs,
   deployment runbooks, and tests for workflow semantics when present.
3. **Select intake assets.** Keep existing repository templates. For a missing
   GitHub template whose creation is explicitly authorized, start from the
   matching file in `assets/` and adapt labels, links, terminology, and supported
   fields before installation.
4. **Map the lifecycle.** Produce one ordered flow: idea or defect, duplicate
   search, issue, approval, claim, branch, local validation, PR, labels, review,
   CI, merge, artifact, deployment, verification, rollback, and closure.
5. **Build the enforcement matrix.** For every policy, record its source,
   owner, enforcement layer, failure mode, recovery path, and whether current
   evidence proves it.
6. **Inspect CI triggers.** Map pull-request, merge-queue, push, schedule,
   manual, release, and deployment events. Detect duplicate work, missing
   coverage, unsafe privileged triggers, and paths that reach production
   without validated evidence.
7. **Inspect CI internals.** Verify permissions, action or image pinning,
   dependency locks, caches, concurrency, timeouts, matrices, service isolation,
   test layers, security scans, artifact retention, and stable required checks.
8. **Inspect governance.** Compare documented issue/PR/label rules with their
   templates, workflow gates, live labels, branch protection, rulesets, roles,
   bypass actors, merge methods, and environment approvals.
9. **Inspect delivery.** Trace the exact source revision into an immutable
   artifact and through promotion. Verify provenance, scanning, smoke testing,
   deployed-revision checks, observability, rollback, and failure notification.
10. **Rank findings.** Use `blocking`, `high`, `medium`, or `low`. Distinguish
   exploitable defects, correctness bugs, governance gaps, operability debt,
   documentation drift, and optional optimization.
11. **Design the smallest coherent change.** Close contradictions across code,
    host configuration, tests, and docs without weakening stronger existing
    controls. State every tradeoff.
12. **Apply only authorized surfaces.** Preserve unrelated work and use the
    target's branch, issue, PR, review, and merge workflow. Never widen remote
    authorization through delegation or tooling.
13. **Test semantics.** Validate syntax plus behavior: event coverage, expected
    skips, fail-closed aggregation, permission denial, label cardinality,
    protected-branch behavior, artifact identity, deploy verification, and
    rollback selection.
14. **Read back authoritative state.** Re-fetch repository files, CI results,
    protections, rulesets, labels, PR state, deployment evidence, and the final
    revision. Report remaining manual or unavailable controls explicitly.

## §5 Output Contract

Return every key, including empty arrays and `null` values.

| Key | Type | Description |
|---|---|---|
| `status` | `success \| blocked \| failed` | Overall result. |
| `target` | `string \| null` | Repository and host inspected. |
| `scope` | `string[]` | Requested lifecycle surfaces. |
| `policy_sources` | `string[]` | Files and live configuration used as evidence. |
| `lifecycle` | `string[]` | Ordered issue-to-production stages found. |
| `enforcement_matrix` | `object[]` | Rule, owner, layer, evidence, and recovery path. |
| `findings` | `object[]` | Severity, defect, evidence, impact, and remediation. |
| `changes` | `string[]` | Local or remote changes applied. |
| `validation` | `string[]` | Commands, checks, and read-backs completed. |
| `manual_controls` | `string[]` | Intentional non-automated controls and owners. |
| `unverified_claims` | `string[]` | Claims not proven by current evidence. |
| `blocked_reasons` | `string[]` | Missing authorization, capability, or evidence. |
| `next_recommended` | `string` | Smallest remaining action, or `none`. |
| `risks` | `string[]` | Residual delivery or governance risks. |

## §6 Anti-patterns

| Symptom | Fix |
|---|---|
| `CONTRIBUTING` says a label is required but no gate or owner exists | Mark it manual with an owner or implement a tested gate. |
| A contributor is told to apply an unauthorized protected label | Route it to verified maintainer authority or automation. |
| CI is green because a required job disappeared or skipped | Make the aggregate gate fail closed on missing or unexpected results. |
| Pull-request validation is removed because merge validation exists | Keep fast PR feedback; use merge-queue validation for integration correctness. |
| Deployment rebuilds source after CI | Promote the immutable artifact already tied to the green revision. |
| A webhook returning success is treated as a healthy deploy | Verify the live revision and a representative smoke path. |
| Admin bypass is used while required checks are red | Fix the checks or policy; bypass only a verified, explicitly permitted rule. |
| Branch protection is documented from memory | Read live protection and rulesets immediately before relying on them. |
| Workflow permissions use broad repository write access | Set default read-only permissions and elevate the smallest job explicitly. |
| Secrets are present in pull-request jobs from external code | Remove secrets and isolate privileged work behind a trusted boundary. |
| A large PR receives an exception without rationale | Split it or document why the diff is indivisible and who accepted the cost. |
| Policy changes land without tests or docs | Add semantic checks and update contributor/operator guidance together. |
| A single required-status-checks list spans jobs from 3+ separate workflow files with no aggregator | Wrap the other workflows as callable jobs so one deterministic gate depends on all of them. |
| Mutation, e2e, or deep-security suites only run on a weekly cron | Also gate them on the release/tag-push trigger, or require a recent green run before publish. |
| A job reachable from `pull_request` declares a self-hosted `runs-on` label | Restrict self-hosted runners to jobs whose `if` statically excludes pull-request-triggered events. |
| An artifact is scanned but never signed before promotion | Sign with a keyless mechanism (Cosign/Sigstore) and verify the signature before deploying. |

## §7 Companion Skills

| Skill | Load when |
|---|---|
| `deterministic-quality-harness` | Converting policy into mechanical ratchets and fail-loud checks. |
| `oracle-vps-github-runners` | The target uses self-hosted GitHub Actions runners on Oracle Linux. |
| `documentation-alan-style` | Writing human-facing contributor, CI/CD, or runbook documentation. |
| Target repository issue/PR skill | Creating issues, branches, PRs, labels, reviews, or merges. |

## §8 References

- `assets/bug-report.yml` — GitHub bug issue form with reproduction evidence.
- `assets/feature-request.yml` — GitHub feature issue form with outcome evidence.
- `assets/documentation.yml` — GitHub documentation issue form with source evidence.
- `assets/maintenance.yml` — GitHub maintenance issue form with operational evidence.
- `assets/refactor.yml` — GitHub refactor issue form with behavior-preservation evidence.
- `assets/pull-request-template.md` — GitHub pull request evidence contract.

- `../deterministic-quality-harness/SKILL.md` — deterministic gate design.
- `../oracle-vps-github-runners/SKILL.md` — self-hosted runner operations.
- `../documentation-alan-style/SKILL.md` — human-facing documentation contract.
- `../skill-style-guide/SKILL.md` — skill authoring and audit contract.
