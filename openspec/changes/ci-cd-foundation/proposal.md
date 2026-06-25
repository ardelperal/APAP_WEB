# Proposal: CI/CD Foundation

## Summary

Establish the APAP_WEB delivery foundation: local quality gates, GitHub Actions CI, and a guarded production deploy trigger through Coolify. This change is documentation/status reconciliation only at this point; no additional CI/CD implementation is introduced by this proposal reconstruction.

## Capabilities

### New Capabilities

- `ci-cd-pipeline` — Defines the repository quality gate, CI workflow, production deploy trigger, operator acceptance evidence, and deferred staging/UAT environment work.

### Modified Capabilities

- None.

## Scope

- Define and verify local commands for tests, linting, and builds.
- Define CI checks for pull requests and pushes on protected release branches.
- Define the production deploy job contract for Coolify.
- Preserve explicit operator-only acceptance tasks for GitHub settings, test PR evidence, secrets, and first deploy evidence.
- Preserve deferred staging/UAT and multi-environment tasks as future-change seeds.

## Out of Scope

- Creating or changing GitHub repository settings.
- Pushing commits, opening PRs, or touching GitHub Actions secrets.
- Implementing new CI/CD code beyond the already-existing repository state.
- Implementing CD-03/ENV-01/UAT/E2E/worker future changes.

## Current Status Note

The original change text assumed an earlier pre-MVC `main`-only policy. The current repo policy uses `staging` for normal work, while production deploy remains guarded on `main`. Status artifacts must distinguish implemented local/CI/CD files from external operator-required evidence.
