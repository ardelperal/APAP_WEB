# CI/CD Pipeline Specification

## Purpose

Define the APAP_WEB quality gate, CI workflow, production deploy trigger, and acceptance evidence required before archiving `ci-cd-foundation`.

## Requirements

### Requirement: Local Quality Gate

The system MUST provide canonical local commands for tests, linting, and builds, and those commands MUST be documented for developers.

#### Scenario: Developer validates locally

- GIVEN a developer has installed project dev dependencies
- WHEN they run the documented test, lint, and build commands
- THEN each command exits successfully or reports actionable failures

#### Scenario: Warnings become failures

- GIVEN a test emits `DeprecationWarning` or `PendingDeprecationWarning`
- WHEN the test suite runs under the canonical pytest configuration
- THEN the warning is treated as a test failure

### Requirement: Continuous Integration Checks

The system MUST run lint, test, and build checks in GitHub Actions for pull requests and pushes on the repository's release branches.

#### Scenario: Pull request validation

- GIVEN a pull request targets a protected release branch
- WHEN GitHub Actions evaluates the workflow
- THEN `ci / lint`, `ci / test`, and `ci / build` are available as required checks

#### Scenario: E2E slot remains explicit

- GIVEN E2E coverage is not part of this foundation change
- WHEN reviewers inspect the workflow
- THEN the E2E integration point is documented without implying completed E2E coverage

### Requirement: Production Deploy Trigger

The system MUST gate production deployment behind successful CI and a push to `main`, and MUST use operator-provided secrets for Coolify.

#### Scenario: Deploy does not run on PRs

- GIVEN a workflow run was triggered by a pull request
- WHEN the deploy job condition is evaluated
- THEN the deploy job is skipped

#### Scenario: Missing webhook URL is a notice (not a failure)

- GIVEN `COOLIFY_WEBHOOK_URL` is not configured
- WHEN a production deploy run reaches the webhook step
- THEN the step exits 0 with a notice that automatic deploys are disabled
- AND the change is still merged (the operator may deploy manually)

> Why not a failure: in pre-MVC staging, the webhook may not yet be configured; a hard fail would block every push to main. The notice gives the operator the signal without breaking the gate.

#### Scenario: Missing webhook secret blocks production deploy

- GIVEN `COOLIFY_WEBHOOK_SECRET` is not configured
- WHEN a production deploy run reaches the webhook step
- THEN the job fails with an explicit configuration error

> Why this one is a failure: without the secret, any payload would be unsigned and Coolify v4 would reject it. Better to fail loud at CI than roll back at runtime.

### Requirement: Coolify Webhook Signing Contract

The deploy step MUST POST a GitHub push payload to the Coolify manual webhook with HMAC SHA-256 over the exact raw request body, and MUST set the signature and event headers Coolify expects.

#### Scenario: Payload shape

- GIVEN a direct push to `main` triggers the deploy job
- WHEN the webhook step builds the request
- THEN the JSON body MUST include `ref` (e.g. `refs/heads/main`), `after` (the full commit SHA), `repository.full_name`, and at least one entry in `commits` with a `message` field
- AND the body MUST be the bytes signed by HMAC — no whitespace reformatting between sign and POST

#### Scenario: Signature header

- GIVEN the body is built
- WHEN the step signs it with HMAC SHA-256 using `COOLIFY_WEBHOOK_SECRET`
- THEN the request MUST include `X-Hub-Signature-256: sha256=<hex>` and `X-GitHub-Event: push`

#### Scenario: Bare curl is not acceptable

- GIVEN the workflow reaches the deploy step
- WHEN the step is implemented
- THEN the workflow MUST NOT contain `curl -fsS -X POST "$COOLIFY_WEBHOOK_URL"` (or any curl variant that POSTs without body or signature)

> Why: Coolify v4's manual github webhook endpoint verifies the raw JSON body against `manual_webhook_secret_github`. An unsigned curl POST would be silently rejected once the secret is set, causing every push to fail with no diagnostic.

### Requirement: Operator Acceptance Evidence

The system MUST NOT mark operator-only tasks complete without external evidence from GitHub settings, PR UI, secrets confirmation, or first deploy run.

#### Scenario: Branch protection evidence missing

- GIVEN branch protection was not verified in GitHub UI or settings JSON
- WHEN SDD status is reviewed
- THEN the branch-protection task remains unchecked and blocks archive readiness

#### Scenario: First deploy evidence missing

- GIVEN no operator-confirmed production dry-run exists
- WHEN SDD status is reviewed
- THEN the dry-run task remains unchecked and blocks archive readiness

### Requirement: Staging Branch and UAT Channel (Deferred)

The system MUST keep CD-03/UAT production-gating work as future-change scope until its trigger condition is met.

#### Scenario: Deferred UAT channel

- GIVEN the staging/UAT channel is not part of this archived change
- WHEN tasks are reviewed
- THEN CD-03/UAT tasks remain unchecked as future-change seeds

#### Scenario: Current staging branch exists without UAT gate

- GIVEN normal work targets `staging`
- WHEN SDD status is reviewed
- THEN this change does not claim UAT-gated production promotion is complete

#### Scenario: Future promotion gate

- GIVEN Virginia MVC/MVP adoption triggers CD-03
- WHEN a future SDD change is opened
- THEN CD-03/UAT tasks are copied or referenced as implementation scope

### Requirement: Staging and Production Coolify Environments (Deferred)

The system MUST keep separate staging/production Coolify environment work as future-change scope until CD-03 is complete.

#### Scenario: Deferred two-environment Coolify setup

- GIVEN separate staging and production Coolify apps are not evidenced here
- WHEN tasks are reviewed
- THEN ENV-01 tasks remain unchecked as future-change seeds

#### Scenario: Existing production deploy remains guarded

- GIVEN production deploy runs on `main`
- WHEN CI/CD status is reviewed
- THEN this change only claims the Coolify webhook trigger, not a two-environment rollout

#### Scenario: Future environment split

- GIVEN CD-03 is complete
- WHEN ENV-01 starts
- THEN staging and production Coolify apps, vars, domains, and health checks are implemented in that future change
