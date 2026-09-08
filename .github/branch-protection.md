# Branch protection for `main`

`main` is the only protected delivery branch during pre-MVP. The repository is
public because the current GitHub plan rejected branch protection while it was
private.

## Required approving review count: 0 (issue #699)

`required_approving_review_count` is deliberately set to `0`.

**Why `0`?** The repository is a single-maintainer project. The sole active
contributor (ardelperal) reviews their own work through the automated gate:
every PR triggers `ci / required`, `pr-name / branch-name` and `pr-size / pr-size`
— three independent, non-skippable automated checks. Requiring a second human
approver on a repo where that human is the author adds friction without safety.

**When to revisit:** if a second human collaborator joins the project, raise this
value to at least `1` and add a `CODEOWNERS` file. The automated gate alone is
not sufficient protection against a compromised or coerced maintainer account.

Evidence: `gh api repos/ardelperal/APAP_WEB/branches/main/protection
--jq '.required_pull_request_reviews'`.

## Required checks

| Check | Purpose |
|---|---|
| `ci / required` | Event-aware, fail-closed aggregation of every applicable CI job. |
| `pr-name / branch-name` | Conventional branch naming. |
| `pr-size / pr-size` | Review-size policy. |

The aggregator accepts skips only where the event contract explicitly permits
them. A missing, cancelled, failed or unexpectedly skipped job fails the check.

## Enforced settings

- Require a pull request before merging.
- Require branches to be up to date before merging.
- Require all conversations to be resolved.
- Include administrators.
- Forbid force pushes and branch deletion.
- Keep linear history disabled because the project requires `--no-ff` merges.

Verify the live rule through the GitHub API after changing workflow job names;
documentation alone does not protect the branch.
