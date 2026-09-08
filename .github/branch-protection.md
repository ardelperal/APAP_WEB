# Branch protection for `main`

`main` is the only protected delivery branch during pre-MVP. The repository is
public because the current GitHub plan rejected branch protection while it was
private.

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
