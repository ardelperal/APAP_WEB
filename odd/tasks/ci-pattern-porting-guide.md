# ci-pattern porting guide + Cadete adoption post-mortem (operator-demanded corrective docs)

Branch: `docs/ci-pattern-porting-guide` off `origin/main` (455ae9b), fresh worktree
`/home/ubuntu/repos/apap-app-worktrees/ci-pattern-porting-guide` — shared checkout untouched.
Refs: #1169, #1170, #1187, `DysTelefonica/cadete#1130`.

## Deliverables
1. `references/porting-guide.md` dual-write: canonical
   `~/personal-skills/personal/ardelperal/ci-pattern/references/porting-guide.md`
   (written first) + APAP mirror `skills/ci-pattern/references/porting-guide.md`.
   Phases 0-5 with hard gates G0.1-G5.2, each citing the Cadete incident (C1-C8) it prevents.
2. `docs/postmortems/2026-09-30-ci-pattern-adoption-cadete.md` — blameless post-mortem of
   the orchestration process (Timeline C1-C8 / Impact / Root cause / What worked /
   What failed / Action items as issues per HR-21). Cited, not copied, from the skill.
3. `odd/tasks/ci-pattern-porting-guide.md` — this record (untracked convention).

## Decisions
- Budget measured: 157 (guide) + ~133 (post-mortem) = ~290 additions < 400 → single PR,
  no size-exception needed.
- Post-mortem lives only in the APAP repo; the skill cites its path
  (`docs/postmortems/2026-09-30-ci-pattern-adoption-cadete.md`), per parent instruction
  «cite, don't copy».
- SKILL.md §8 References left untouched: SKILL.md is outside the allowed edit
  surfaces. Flagged for the parent.

## Flag for the parent (human decision before push)
Branch name `docs/ci-pattern-porting-guide` (as ordered) lacks the issue number required by
`<tipo>/<N>-<slug>` (HR-7 / `check_branch_name.py`) — the exact failure class cited as C3.
Precedent: mirror PR #1173 used `docs/1169-ci-pattern-mirror`. Alternative:
`docs/1170-ci-pattern-porting-guide`. Worktree/branch rename is trivial pre-push.

## Proposed commits (parent owns git)
- `docs(ci): add ci-pattern porting guide reference (Refs #1169, #1170, #1187)`
  + body line: `Refs DysTelefonica/cadete#1130`
- Post-mortem in the same PR (budget fits) or as the chained tip:
  `docs(postmortem): add Cadete ci-pattern adoption post-mortem (Refs #1169, #1170, #1187)`
- No AI attribution (HR-14).

## Verification
- `check_alantyle.py` exit 0 on all touched files: see handoff validation.
- Every phase gate cites its real incident: inline C-N citations, traceability table at the end.
