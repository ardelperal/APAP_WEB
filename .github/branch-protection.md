# Branch protection for active protected branches

Configure the active protected branch policy so every pull request is gated by the CI workflow before merge. For normal APAP_WEB work, protect `staging`; protect `main` as the production branch if the operator requires direct production/release PRs.

## Required checks

Add these required status checks:

| Check | Source |
|-------|--------|
| `ci / lint` | Ruff lint job |
| `ci / test` | Pytest job with deprecations as errors |
| `ci / build` | Python package build job |

## GitHub setup path

1. Open the repository in GitHub.
2. Go to **Settings → Branches → Branch protection rules**.
3. Create or edit the rule for `staging` (normal work) and, if required, `main` (production/release).
4. Enable **Require status checks to pass before merging**.
5. Select `ci / lint`, `ci / test`, and `ci / build`.
6. Enable **Require a pull request before merging**.
7. Set the operator-approved required-reviewer count.
8. Save the rule.

## Operator evidence

Before marking SDD task `1.5` complete, attach one of these to the PR comment:

- A screenshot of the active protected branch rule (`staging` for normal work; `main` for production if required) showing the three required checks.
- The GitHub settings JSON or audit output showing the same rule.

Do not store screenshots containing secrets in the repository.
