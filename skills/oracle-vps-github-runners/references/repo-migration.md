# Migrating a repository onto the pool

Ordered, because the failures are ordered. Everything here was observed moving
`ardelperal/APAP_WEB` from GitHub-hosted runners to this pool on 2026-08-11.

## Before you move anything

**Check whether the move is even warranted.** Hosted minutes are free for public
repositories and billed for private ones. A private repo that exhausted its quota
has a real reason; a public one is paying complexity for nothing. Also check who
owns the billing: a repo in an organisation and a repo under a personal account
draw from different quotas, so a routing decision that is correct in one is not
portable to the other.

**Measure the wall clock first.** Write down each job's duration. You will be
asked whether a second runner is worth it, and the answer usually is not: on
APAP_WEB the whole critical path was dominated by a single 123-second test job,
so a second runner bought ~2 minutes. A pool grows for *redundancy*, not speed.

## The move itself

1. Change every `runs-on` to the pool's exact labels. Never `-latest`.
2. **Add `actions/setup-python` to every job that runs a `python` command.** The
   hosted image had an interpreter; this one does not. The jobs that break are
   the ones that never needed the step before, so they are also the ones nobody
   thinks to check.
3. **Grep every `run:` block for `gh`.** Rewrite as curl + jq. See
   `assets/repo-ci-hardening.yml` block 6.
4. Apply blocks 1–5 of that file. Blocks 1 and 4 are prerequisites for ever
   adding a second runner.
5. Update the comments you invalidated. A `runs-on` rationale that still argues
   for the runner you just left is worse than no comment: the next reader trusts
   it.

## After the first merge — do not skip this

**Green PR checks do not mean the merge succeeded.** A `pull_request` run and a
`push`-triggered workflow are different runs with different contexts, and the
second one is where a migration breaks.

On APAP_WEB, four consecutive merges landed with every PR check green while the
`deploy` workflow failed each time. Nobody noticed for two days, because nobody
looks at a workflow that runs *after* the thing they were watching. The cause was
block 6: `gh` was absent, and the error was laundered into a legitimate-looking
"this tree was never proven".

So after the first merge, read the post-merge run list, not the PR:

```sh
gh run list --workflow deploy --limit 5 \
  --json conclusion,headSha -q '.[] | "\(.conclusion) \(.headSha[0:8])"'
```

Compare against the last known-good deploy. If the boundary lines up with your
migration commit, the migration caused it.

## Writing the gates that keep it true

Applying the hygiene by hand is half the work; nothing stops the next job from
omitting it. Every block above should ship with a check, and these three
properties are what separate a check from decoration:

**It must be provable that it can fail.** Reintroduce the defect on the real
tree — not only in a synthetic fixture — and watch the gate reject it. A gate
that has never failed is indistinguishable from one that cannot.

**It must ignore comment lines.** The file usually documents the very command it
stopped using, so a scanner that reads comments reports the explanation as the
offence. That teaches people to delete explanations, which is a worse outcome
than the defect. This bites the tests too: an `assert "|| echo 0" not in text`
fails on the comment describing its removal.

**Word boundaries matter.** A bare search for `gh` matches `through`, `high` and
`enough`. Anchor on invocation position.

## Ordering rule when several checks share a file

Run the *parse-integrity* check first, with its own scanner, and stop if it
fails. A YAML library will happily accept duplicate keys and keep the last one,
so any conclusion drawn past an ambiguous key is arbitrary — the duplicate is
the finding, and the rest must wait.
