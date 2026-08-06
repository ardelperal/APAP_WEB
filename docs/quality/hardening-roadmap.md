# Quality harness — roadmap and handoff

**Purpose.** This document lets a different agent (or a future session) continue
the code-quality hardening work without re-deriving what was already measured.
Everything below was verified by running it on 2026-08-06, not inferred.

Read this before touching `scripts/check_*.py`, `docs/quality/`, the `mutation`
job in `ci.yml`, or AGENTS.md §34.

Source of the discipline: [unclebob/swarm-forge](https://github.com/unclebob/swarm-forge),
adapted from its agent-role model to this repo's gate model. Tracking issues:
#428 (PR #1), #431 (PR #2), #433, #434, #435.

---

## 1. State of play

### Done and pushed

PR #432 (draft, branch `feat/quality-gates-mutation`, stacked on
`feat/quality-gates-foundations` — **do not merge before PR #1 / #428**):

| Artifact | What it does |
|---|---|
| `scripts/check_mutation.py` | Degenerate-run guard + shrink-only survivor ratchet |
| `tests/test_check_mutation.py` | 24 tests over synthetic sessions; green on Windows |
| `docs/quality/cosmic-ray.toml` | Pilot target + mandatory equivalent-mutant filter |
| `docs/quality/mutation-baseline.json` | `migration/derivation.py: 38`, platform-labelled, PROVISIONAL |
| `docs/runbooks/mutation-testing.md` | WSL setup, acquisition, failure decoding |
| `ci.yml` → `mutation` job | Schedule + `workflow_dispatch` only, never per-PR |
| `tests/test_ci_workflow.py` | 4 pins: gate, filter, triggers, `PYTHONHASHSEED` |
| `Makefile` → `mutation` | Refuses to run outside Linux |
| `AGENTS.md` §34 | The doctrine behind all of it |

### The open wound — fix this first

```
$ git log --all --oneline -- scripts/check_layers.py
(empty)
```

`scripts/check_layers.py` (556 lines), `tests/test_layers.py` (14.5 KB) and
`docs/architecture/capas-y-slices.md` (5.6 KB) exist **only as uncommitted files
in the main checkout's working tree**. Never committed on any branch. `rg -c
check_layers` returns 0 against both `origin/main`'s and this branch's `ci.yml`.

**Consequence: there is no deterministic architecture enforcement running
anywhere today.** AGENTS.md §33 (slice location) is on `origin/main`; its gate is
not. That is §32.P3 applied to the most important rule in the repo, and the
harness survives only as local disk state on one machine.

The gate itself is good — three explicit axes, `ALLOWED_IMPORTS` rather than an
implied ordering, only 4 baseline entries each with a written justification, a
test that detects stale entries. It is a well-built gate that is switched off.

**Also note:** the main checkout has ~204 uncommitted files (the hexagonal
vertical-slice refactor of epic #420 in flight). Do not clobber it. Work in a
worktree.

---

## 2. Ordered plan

### Step 1 — Commit the hexagonal harness (severity: everything else is secondary)

- Rescue `scripts/check_layers.py`, `tests/test_layers.py`,
  `docs/architecture/capas-y-slices.md` from the working tree onto a branch.
- Wire `python scripts/check_layers.py` into the `lint` job of `ci.yml`, after
  the route-size ratchet.
- Pin the step with `tests/test_layers.py::test_ci_workflow_lint_job_runs_layers_gate`
  using the `_job_executable(workflow, "\n  lint:", "\n  security:")` helper
  already in `tests/test_ci_workflow.py`.
- Update AGENTS.md §33's Enforcement line: it currently says PR review; it should
  name the gate.

Until this lands, every later step rests on nothing.

### Step 2 — Slice-completeness gate (the real gap)

`check_layers.py` proves *"no forbidden import"*. That is necessary and nowhere
near sufficient for "real hexagonal". Nothing today proves a slice is **complete**.

Build a gate that, for each slice under `app/core/<layer>/<slice>/` and
`app/modules/<slice>/`, asserts:

- a port Protocol is declared in `ports/` for every outbound dependency;
- the adapter is constructed in `app/core/di/` and **injected**, never imported
  by the application layer (partially covered by axis 1 — make it explicit);
- the application layer imports no concrete adapter symbol;
- each layer of the slice has at least one test file.

Shrink-only `BASELINE` for slices that predate the gate, same contract as the
other ratchets. This is what turns "hexagonal" from declarative into verifiable.

### Step 3 — Extend the layer gate to `migration/`

`SCAN_DIRS = ("app",)` today. `migration/` is excluded by a comment calling it a
standalone ETL tool — but it holds the most complex code in the repo
(`reconcile.py` 976 LOC, `apply.py` 869, `diff_engine.py` 642). Either extend the
gate or give `migration/` its own explicit boundary gate. Do not leave it
unstated.

### Step 4 — Architecture reviewer agent (complement, never the guarantee)

A skill/subagent that reviews a diff against §31/§33/§34 and reports findings,
referenced from AGENTS.md.

**State its scope honestly in the file itself:** an LLM reviewer is
non-deterministic and cannot be the thing that "cannot be deviated from". It is a
second read for judgement-level concerns no AST can see. If the guarantee rests
on it, there is no guarantee — the determinism lives in the gates. This is
AGENTS.md §34.3 applied to the reviewer itself.

### Step 5 — Grow the mutation target set (#434)

Ordered by measured density. One module per PR, each with its baseline entry
acquired **on Linux**.

### Step 6 — Kill the pilot's survivors (#433) and close the query-test gap (#435)

### Step 7 — Process gates that only exist as prose

Each of these is a rule the repo already declares and does not enforce — §32.P3
in four more places. All are cheap; none block anything, so do not let them jump
ahead of steps 1–3.

- **#442 — PR size gate.** §15.1 declares a 400-line review budget. Verified
  2026-08-06: nothing enforces it, there is no `pr-check.yml`. The budget lives
  in `CLAUDE.md` as prose aimed at a well-behaved agent. `gentle-ai` enforces the
  equivalent deterministically. The reframe that matters: with an LLM reviewing
  the diff, reviewer fatigue stops being the argument — revert granularity,
  all-or-nothing approval pressure, and hidden omissions remain. And because
  agents write this code, the budget is a **design** constraint: it forces
  decomposition.
- **#443 — import-cycle detector.** 19 `lazy-import:` markers across 7 files,
  against §26's own claim of "exactly two" on 2026-07-20 — ~10× in 17 days. §26
  demands a comment, not a fix, so it legitimised the debt; `check_layers.py`
  only sees cycles that cross layers. Reuses the graph `check_layers.py` already
  builds (Tarjan SCC, ~70 lines).
- **#440 — §15.2 rewrite.** Policy changed 2026-08-06: merged branches are
  **kept**, not deleted, and adopt `<type>/<issue>-<slug>`. Note for whoever
  writes it: deleting a ref never deleted commits (`--no-ff` keeps them in
  `main`, and GitHub retains `refs/pull/<n>/head` forever), so the benefit is
  narrower than it looks while the cost — dead refs indistinguishable from live
  ones — is immediate. Naming is what makes retention viable.
- **#441 — branch-name gate.** Enforces #440's convention. Depends on it.

### Not adopted, and why

[fallow.tools](https://fallow.tools/) was evaluated 2026-08-06 (user request).
**TypeScript/JavaScript only** — this repo is Python plus a Windows-only
Access/VBA half, so there is no surface for it. Of its feature set, only
circular-dependency detection was a genuine gap (now #443); unused code,
duplication, complexity and architecture boundaries are already covered by
`check_vulture_guard.py`, `check_jscpd.py`, `check_complexity.py` and
`check_layers.py`. Its paid runtime layer (hot/cold paths, deletion confidence)
is a good idea with no data behind it here — revisit post-MVP, when production
traffic exists.

CodeRabbit was evaluated the same day. It is an **AI PR reviewer, not a runner**
— the runner already exists (self-hosted Oracle ARM64). Self-hosting it is
enterprise-tier (~$15k/month floor). As another LLM reviewer it lands in the same
category as `judgment-day` / `code-review-expert`: a useful second read, never
the determinism. What *is* worth copying from `Gentleman-Programming/gentle-ai`
is its `pr-check.yml` — deterministic process gates (size, issue reference,
`status:approved`, `type:*` label), which is what #442 does.

---

## 3. Hard-won facts — do not re-derive these

### Mutation tooling

1. **cosmic-ray 8.4.6 does not work on native Windows.** 100% of mutants come
   back `INCOMPETENT` — measured 27/27 on a 12-line control module and 233/233
   on `migration/derivation.py`. The same control module on WSL returns 27/27
   `KILLED`.
2. **`cr-rate` cannot detect this.** It reports `0.00` and exits 0 for both a
   perfect run and a run where nothing executed. `cr-rate --fail-over 20` passes
   on the broken session. This is why `scripts/check_mutation.py` exists.
3. **`mutmut` 3.7.0 refuses to start on Windows** by design (upstream
   boxed/mutmut#397). Not an alternative.
4. **`cosmic-ray exec` has no `--worker-count` option** in 8.4.6, and the `local`
   distributor is already sequential. TASK-2.1's W-5 flag does not exist.
   `PYTHONHASHSEED=0` is real and is kept.
5. **The worker spawns without a shell**, so a bare `python` in `test-command`
   may not resolve. `cosmic-ray baseline` then fails with a near-empty error
   block. When that happens, run the `test-command` by hand — the real cause
   surfaces only that way. (It was a missing `pytest-cov` making `--no-cov`
   unrecognised.)
6. **PEP 604 annotation mutants are unkillable.** `ReplaceBinaryOperator_BitOr_*`
   mutates the `|` in `str | None`; with `from __future__ import annotations`
   those never evaluate. On the pilot they were **66 of 104 reported survivors**
   — 63% noise. `cr-filter-operators` between `init` and `exec` is mandatory.
7. **Filtered mutants carry `worker_outcome = SKIPPED` and a NULL
   `test_outcome`.** They are neither pending nor results. Reading them as
   pending rejects every filtered session as incomplete — a real defect that was
   found and fixed in `check_mutation.py`.
8. **Session schema** (verified against a real session): tables `work_items`,
   `mutation_specs`, `work_results`; outcomes stored as SQLAlchemy member
   **names** (`KILLED`), while `TestOutcome` is a `StrEnum` whose values are
   lowercase. Normalise both.

### Where mutation testing pays, and where it does not

Measured mutable AST sites (`Compare`/`BoolOp`/`BinOp`/`not`/`AugAssign`/branch):
**3579 across 217 files** in `app/` + `migration/`. A whole-tree session runs for
days — `module-path = "app"` is not viable.

The §22 "pure seam" is almost empty of mutable sites, because no mainstream
Python engine mutates string literals:

| Module | LOC | Sites |
|---|---:|---:|
| `salud/queries.py` | 313 | **2** |
| `sanidad/queries.py` | 308 | 4 |
| `adopciones/queries.py` | 272 | 14 |
| `animals/queries.py` | 238 | **65** |

Highest-value targets, by density:

| Module | LOC | Sites | /100 LOC |
|---|---:|---:|---:|
| `migration/derivation.py` | 396 | 84 | 21.2 ✅ pilot |
| `app/modules/adopciones/service.py` | 527 | 110 | 20.9 |
| `migration/diff_engine.py` | 642 | 131 | 20.4 |
| `app/core/insforge.py` | 690 | 112 | 16.2 |
| `app/modules/animals/queries.py` | 238 | 65 | 27.3 (blocked on #435) |

### Environment

- **WSL recipe that works** (Ubuntu 22.04, `python3-venv` is absent and needs
  sudo, so use user-site):
  ```bash
  pip3 install -q --user --break-system-packages pytest pytest-cov pytest-asyncio \
      cosmic-ray fastapi starlette jinja2 pydantic pydantic-settings \
      python-multipart httpx itsdangerous rapidfuzz
  ```
- **Copy the tree to WSL's native filesystem.** Measured on the same test:
  `~/` 0.10 s, Windows native 0.16 s, **`/mnt/c` 4.52 s (45× penalty)**. Also,
  cosmic-ray mutates files in place — never point it at a live worktree.
- **`pytest-randomly` is pinned on `feat/quality-gates-foundations`.** If it is
  missing locally, the suite aborts on `--randomly-dont-reorganize`. Run with
  `-o addopts=""`. CI is the authority for a full-suite verdict.
- **`make` is not installed on the Windows workstation.** Verify Makefile recipes
  by reasoning or under WSL.

---

## 4. Standing judgement on the harness

Recorded so the next agent inherits the assessment, not just the artifacts.

**Genuinely strong:** mypy at zero errors over 216 files (binary, no ratchet, no
escape). The ratchet pattern itself — better brownfield engineering than the
source repo, which has no such story.

**Weak, and honestly so:**

- **Architecture is not enforced at all today** (§1 above). Highest severity.
- **The mutation gate covers 1 module of 217 — 0.46%.** It is a real instrument
  at pilot scope. It does not yet provide assurance about the codebase; it
  provides a method and a first measurement. Do not oversell it.
- **Ratchets freeze debt, they do not reduce it.** `check_ruff_ratchet` tolerates
  434 findings; jscpd tolerates 1.88% duplication. The repo can sit at baseline
  forever with every gate green. Ratchets stop growth; a separate, deliberate
  effort reduces the stock.
- **Coverage floors measure execution, not assertion.** That gap is exactly what
  the mutation gate exists to close, and it is 0.46% closed.

**The rule to carry forward (AGENTS.md §34.3):** when you add a quality metric,
write down what a broken measurement looks like and make the gate fail on it. A
metric whose failure mode is silence is worse than no metric, because it
manufactures confidence.
