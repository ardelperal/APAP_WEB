<!-- HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — assets/README.md -->

# Assets — reference implementation of the harness

These files are **templates**, not the live gates. The live copies belong in the consuming
repository (`scripts/`, `tests/`, `.github/workflows/`). Two live copies of the same script is
drift, and drift is Hard Rule 10.

## Instantiation contract

1. Copy the file into the consuming repo at the path listed below.
2. Keep the `HARNESS-PROVENANCE` line at the top of every copied file. It records which version of
   this skill produced it, so a later audit can tell an intentional local edit from silent drift.
3. Adjust only the clearly marked configuration block at the top. Everything below it is mechanism.
4. Run `pytest tests/test_gate_smoke.py` immediately. A gate that has never been observed failing is
   not yet a gate (Execution Step 5).
5. Protect the entrypoint's line endings. `Makefile` must stay LF — a stray `\r` in a recipe breaks
   it on the Linux runner, and Windows editors and `sed -i` both convert files silently. One line
   in the consuming repo's `.gitattributes` closes it for good (Hard Rule 19):

   ```gitattributes
   Makefile text eol=lf
   ```

| Asset | Destination in the consuming repo |
|---|---|
| `Makefile` | `Makefile` (merge into an existing one; keep `verify`) |
| `ci.yml` | `.github/workflows/ci.yml` |
| `quality-policy.json` | `quality-policy.json` |
| `scripts/quality_policy.py` | `scripts/quality_policy.py` |
| `scripts/check_layers.py` | `scripts/check_layers.py` |
| `scripts/check_complexity.py` | `scripts/check_complexity.py` |
| `scripts/check_crap.py` | `scripts/check_crap.py` |
| `scripts/check_dry.py` | `scripts/check_dry.py` |
| `scripts/check_mutation_sites.py` | `scripts/check_mutation_sites.py` |
| `scripts/check_mutation.py` | `scripts/check_mutation.py` |
| `scripts/quality_report.py` | `scripts/quality_report.py` |
| `scripts/check_pr_size.py` | `scripts/check_pr_size.py` |
| `scripts/check_branch_name.py` | `scripts/check_branch_name.py` |
| `scripts/check_adoption.py` | `scripts/check_adoption.py` |
| `scripts/policy_time.py` | `scripts/policy_time.py` |
| `cosmic-ray.toml` | `cosmic-ray.toml` |
| `security-images.sources.json` | `security-images.sources.json` |
| `security-images.lock.json` | `security-images.lock.json` |
| `tests/test_ci_workflow.py` | `tests/test_ci_workflow.py` |
| `tests/test_gate_smoke.py` | `tests/test_gate_smoke.py` |
| `tests/test_gate_liveness.py` | `tests/test_gate_liveness.py` |
| `tests/test_adoption_preflight.py` | `tests/test_adoption_preflight.py` |
| `tests/test_policy_time.py` | `tests/test_policy_time.py` |
| `tests/test_quality_policy.py` | `tests/test_quality_policy.py` |
| `tests/test_quality_report_contract.py` | `tests/test_quality_report_contract.py` |
| `tests/fixtures/**` | `tests/fixtures/**` |
| `pyproject.fragment.toml` | merged into `pyproject.toml` |

## What each asset enforces

| Asset | Hard Rule it makes executable |
|---|---|
| `Makefile` | 19 (`verify` is the one command that equals green), 13 (the order is the same as ci.yml's) |
| `ci.yml` | 1 (no `\|\| true`, no `continue-on-error`), 4 (every gate wired), 15 (runner and actions pinned) |
| `quality-policy.json` | 11, 12, 14, 16: canonical subjects, exclusions, owners, non-ownership, ceilings, and command identities |
| `quality_policy.py` | 14, 16, 17: ordered content-bound manifest plus candidate, policy, scope, and tool evidence |
| `check_layers.py` | 9 (AST, not regex), 12 (ratchet with target and expiry date), 14 (declared testable boundary) |
| `check_complexity.py` | 12 (absolute global ceiling — never `top-N`) |
| `check_crap.py` | 12, plus the complexity-against-coverage axis; fails closed without coverage data |
| `check_dry.py` | 17 (sha256 over a normalised AST — never `hash()`, which is salted per process) |
| `check_mutation_sites.py` | 12; the per-file surface that no per-function gate can see |
| `check_mutation.py` | 18 (degenerate-run guard), 12 (survivor ratchet + acquisition grace) |
| `quality_report.py` | 13 (gate order pinned in code), 16 (indicators plus mismatch/stale-evidence rejection) |
| `check_pr_size.py` | Decision Gate "PR exceeds 400-line review budget" |
| `check_branch_name.py` | Naming discipline, allowlisted defaults only |
| `check_adoption.py` | 2, 6, 14, 15, 18: required configs and locks exist; coverage and mutation roots match policy |
| `policy_time.py` | 12, 17: ratchet expiry receives a validated, recorded input instead of reading the clock |
| `test_ci_workflow.py` | 4 (wiring pin, per gate AND over the whole set), 19 (`make verify` <-> ci.yml parity), and re-asserts 1, 13 and 15 mechanically |
| `test_gate_smoke.py` | Execution Step 5 (each gate observed exiting 1 on a real violation), 17 |
| `test_gate_liveness.py` | 18: empty, missing, or unmeasured subjects fail closed instead of scoring clean |
| `test_quality_policy.py` | 14, 16, 17: policy validity, deterministic manifest identity, and fail-closed denominator |
| `test_quality_report_contract.py` | 16: subprocess contract, identity mismatch, and evidence-reuse rejection |

## Candidate- and scope-bound evidence

`quality-policy.json` is the only editable authority for governed subjects, exclusions, owners,
non-ownership, ceilings, and command identities. The Python gates consume it through
`scripts/quality_policy.py`; `check_adoption.py` rejects coverage or Cosmic Ray roots that drift
from it. Every governed envelope contains the same ordered, content-hashed subject manifest and
candidate commit/tree, while its subject accounting names exactly what was checked, skipped, or
unclassified. `quality_report.py` recomputes those identities at aggregation time, so evidence
from another candidate or evidence reused after a source change fails closed.

## Resolving the action pins

`ci.yml` ships with real commit SHAs resolved at authoring time. Re-resolve them before adopting,
and on every action upgrade:

```bash
gh api repos/actions/checkout/releases/latest --jq .tag_name
gh api repos/actions/checkout/git/ref/tags/<tag> --jq .object.sha
```

Never move an action back to a floating tag to "fix" a failure. Hard Rule 15 exists because a
floating tag turns a green gate red with no code change.

## Completing the adoption locks

The template deliberately does not ship a generic `requirements-dev.lock`: its complete graph
depends on the consuming project's metadata and target Python. Generate it from the copied and
merged `pyproject.toml`, then let both pip and the preflight verify it:

```bash
python -m pip install pip-tools==7.6.1
python -m piptools compile --extra dev --generate-hashes \
  --output-file requirements-dev.lock pyproject.toml
python scripts/check_adoption.py
python -m pip install --require-hashes --requirement requirements-dev.lock
```

`check_adoption.py` requires the hash-locked file to contain `cosmic-ray==8.7.0` and rejects a
missing or unhashed mutation pin before CI can claim the mutation job is configured.

Scanner tags are inputs to an explicit upgrade, never CI inputs. The committed
`security-images.lock.json` contains the registry manifest digests resolved for the exact tags in
`security-images.sources.json`. CI reads only the resulting `name:tag@sha256:...` references.
To upgrade, edit an exact source tag, resolve it while the registry is reachable, inspect the
diff, commit both files, and run the preflight:

```bash
python scripts/check_adoption.py --resolve-security-images
git diff -- security-images.sources.json security-images.lock.json
python scripts/check_adoption.py
```

Resolution uses `docker buildx imagetools inspect` and fails closed on a missing client, registry
error, malformed response, placeholder, or non-SHA-256 digest. The shipped digests were resolved
from their registries on 2026-08-12; re-resolution is an explicit upgrade operation, never a
network dependency of CI.

## Running the gates locally

```bash
make verify POLICY_DATE=2026-08-12
```

That is the whole contract (Hard Rule 19). It runs every gate `ci.yml` applies to a pull request,
in the same order, and `tests/test_ci_workflow.py` fails if the two lists ever disagree. If it
passes on a branch that is up to date with `main`, CI has nothing left to discover.

What `verify` does under the hood, should you need a single step on its own:

```bash
pytest --cov --cov-report=json:coverage.json   # CRAP consumes coverage.json
python scripts/quality_report.py --policy-date 2026-08-12
                                               # layers -> complexity -> CRAP -> DRY, in order
```

`quality_report.py` writes `quality-report.json` and prints the indicator table. Any single gate
also runs standalone, with `--root` to point it elsewhere and `--json` for its raw envelope:

```bash
python scripts/check_crap.py --root . --policy-date 2026-08-12 --json
```

## Reproducible analysis and policy expiry

Measurement is code-only; expiry is policy. Every ratchet gate therefore requires one canonical
`--policy-date YYYY-MM-DD`, uses it for both expiry and baseline generation, and records it in its
JSON envelope. Fixed commit plus fixed policy date produces byte-identical evidence. Advancing the
date is an explicit new policy evaluation and can correctly turn an expired allowance red.

CI obtains UTC time once per job at the orchestration boundary, exports `POLICY_DATE` through
`GITHUB_ENV`, writes it to `GITHUB_STEP_SUMMARY`, and passes the same value to the aggregator or
mutation gate. Gates themselves never call `date.today()`. For local replay, copy the recorded
date from the report or job summary:

```bash
make verify POLICY_DATE=2026-08-12
```

Do not default `POLICY_DATE` to the current date in the Makefile. Requiring the caller to name it
is what distinguishes reproducible evidence from time-dependent policy enforcement without
weakening `target_date`: expired entries still fail when evaluated at the supplied date.

## Deliberate scope limits

- **Mutation configuration and tooling ship complete, but the consuming suite remains the proof.**
  Local and CI runs use the same root `cosmic-ray.toml`, Cosmic Ray is pinned in the dev lock,
  and adoption fails before a config or lock can be missing. A real session still depends on the
  consuming codebase and tests, so run `make mutation` once before trusting its first green.
- **Mutation runs weekly, not per PR**, and that is why CRAP stays: CRAP is the per-PR proxy,
  mutation is the periodic ground truth. CRAP trusts the coverage number and coverage counts a
  line as covered whether or not any assertion looked at it — which is precisely the blind spot
  mutation closes.
- **No coverage floor gate ships here.** Coverage is published as an indicator, but the floor
  belongs to `pytest --cov-fail-under` so that one tool owns one verdict — and it is meaningless
  until the consuming repo declares its testable/untestable boundary (Hard Rule 14).
- **`CRAP <= 6` dominates `CC <= 15`.** At full coverage CRAP equals complexity, so no function
  above complexity 6 can pass. That is upstream's number, kept deliberately. If it is too strict
  for your codebase, raise `MAX_CRAP` explicitly and record why — do not discover it by accident.
