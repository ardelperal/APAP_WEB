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

#### Scenario: Missing deploy secret blocks production deploy

- GIVEN `COOLIFY_WEBHOOK_URL` is not configured
- WHEN a production deploy run reaches the webhook step
- THEN the job fails with an explicit configuration error

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
