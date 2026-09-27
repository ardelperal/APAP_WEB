# Main-history audit + multi-session push prohibition (#986)

Work-unit commits on `chore/986-main-audit-trail` (this PR + follow-up):

1. `ci(gobernanza): scheduled main-history audit for direct pushes` — workflow,
   script, tests, this odd/tasks evidence.
2. `docs(gobernanza): multi-session push prohibition aligned with #986` — docs
   alignment (follow-up PR per the 400-line budget cap).

Detection: walk the last 30 commits of `origin/main`; a commit is "expected"
when it sits on the first-parent chain OR is reachable from the second parent
of a merge commit of PR on `main`. Anything else is "unexpected" (= push
directo) and gets listed in the tracking issue. Verified against #1016,
#1021, #1022: 0 false positives on intermediate commits.

PR #N: <filled at PR creation>.