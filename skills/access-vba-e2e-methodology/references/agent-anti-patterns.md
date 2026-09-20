# Agent's own anti-patterns + TDD workflow discipline with the user

These are anti-patterns of the AI agent, not of the project's code. The forms-thin-refactor session exhibited all of them and wasted the user's time.

## TDD workflow discipline (the compile/test cycle)

The agent repeatedly tried to run `dysflow.test_vba` BEFORE the binario was compiled, and the failure was hard to debug. Lesson learned.

**Who compiles depends on whether the change touches forms:**

| Change scope | Who compiles | How |
|---|---|---|
| **No form changes** (only `.bas` modules: helpers, tests, services) | **The user**, manually | User runs **Debug ▸ Compile** in Access; agent waits for confirmation |
| **Form changes** (`.cls` form behavior, `.form.txt` layout/wiring) | **The user**, manually | User runs **Debug → Compile** in VBE; agent waits for "OK" |

Hard rules:

- **Never run `dysflow.test_vba` against a non-compiled binario.** It produces HRESULT errors unrelated to test logic and wastes a round-trip. Always wait for the user's compile confirmation BEFORE testing.
- **The agent NEVER compiles — no exception for module-only changes.** `compile_vba` is absent from the live dysflow schema index, and `import_modules` / `import_all` carry no `compile` parameter. The user runs Debug → Compile in Access and confirms "OK"; only then run `test_vba`. Form compilation additionally opens VBE modals that block COM.
- **Compile between imports, not in batches.** Import one `.bas` at a time and compile before the next. If you import three at once and one is broken, you cannot tell which. VBA's incremental compile dominates compile time, not import — this does NOT make the workflow slower.
- **On a compile error, do not guess — follow the compile-error protocol** in `helper-naming.md`. For user-side compile errors, ask for the exact VBE dialog text first.

## Agent anti-patterns

- **Running `dysflow.test_vba` before the binario compiled.** The binario is "modules imported, code present, not reconciled by VBA". Wait for the user's compile confirmation, then run tests.
- **Reaching for a compile tool at all.** `dysflow.compile_vba` does not exist in the runtime; hand every compile off to the user.
- **Blaming the user's environment for the agent's own mistakes.** When a compile error appears, the first reaction must be "I made a mistake; let me check my changes first" — NOT "your binario is broken" or "you have legacy ambiguity". Only after exhausting your own changes consider the environment.
- **Inventing public function names without checking what exists.** Run the collision audit (`helper-naming.md`) or use the per-module prefix and the problem disappears.
- **Editing `.form.txt` `CodeBehindForm` blocks.** Dysflow overwrites them from the `.cls` on every import. Edit the `.cls`; the `.form.txt` block is futile.
- **Refusing to revert and start over.** When a sub-agent's work is partially wrong, it is usually faster to `git checkout` the affected files, `git stash` the salvageable work, and redo inline. Do not let sunk-cost fallacy keep you editing the wrong file.
- **Marking todos "completed" before verification.** A todo is "completed" only when (a) the diff matches the plan, (b) the user has compiled, (c) `dysflow.test_vba` is green, (d) the commit exists. Anything less is "in progress" or "blocked".
- **Delivering prose without verifiable artifacts.** Every "done" claim MUST include: file paths (absolute or repo-relative), diff stat, test count, and the Dysflow import response. "I've applied the change" without these is unverifiable; the user has to re-do your audit.
- **Writing code against assumed schema/entity/control/method shapes.** Never invent entity properties, call non-existent methods, reference unverified form controls, or write SQL against unchecked tables. See `preflight-audit.md` — the 4 audits are mandatory before any code.
