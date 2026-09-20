---
name: deterministic-quality-harness
description: Trigger: deterministic code quality, ratchet gate, shrink-only baseline, fail-loud gate. Enforce criteria via mechanical self-policing gates.
license: Apache-2.0
metadata:
  author: ardelperal
  version: 1.8
  last_verified: 2026-09-05
  scope: ['universal', 'docs']
  auto_invoke: ['auditing CI quality gates', 'setting ratchet baselines']
  tiers: ['universal', 'docs']
---



## Activation Contract

Load when authoring or auditing CI quality gates; adding lint, complexity, dependency, secret,
mutation, or coverage rules; setting a ratchet baseline; wiring a gate; or diagnosing a gate that
runs but cannot fail. Do not load for style advice, human-only review checklists, or naming guidance
that does not affect an executable gate.

## Hard Rules

1. **Fail loudly.** A scanner wrapped in `|| true`, `continue-on-error`, or lossy filtering is not a gate.
2. **Pin governing tools exactly.** Pin tool, transitive dependency, runner, action SHA, and scanner digest inputs.
3. **Ratchet stable finding identities.** New identities fail; removed debt locks in; migrate aggregate baselines explicitly with `--emit-baseline`.
4. **Pin wiring at set level.** Compare every `scripts/check_*.py`, CI gate, and local entrypoint gate; per-gate lists can omit the same new gate twice.
5. **Do not ignore antipattern lint rules silently.** Fix the code or document the narrow exception inline.
6. **Pin scanner images by digest.** Mutable tags are upgrade inputs, never CI execution inputs.
7. **Keep vulnerability allowlists shrink-only.** Every ignored ID links to an open issue.
8. **Mutate `session.exitstatus` in pytest contracts.** Changing `config.exitstatus` does not change the process result; verify with `pytester`.
9. **Enforce pure layers with AST analysis.** Regex is not a reliable import-boundary parser.
10. **Repair documentation drift in the detecting change.** Do not defer known contract divergence.
11. **Declare segregated ownership.** Every gate names its runner, owner, and explicit non-ownership; authors do not self-certify.
12. **Set an absolute ceiling before a ratchet.** Every allowance has a target and target date; never use relative `top-N` verdicts.
13. **Run gates in one fixed order and fix between steps.** Reordering must not change the resulting candidate.
14. **Use one versioned testability policy.** `quality-policy.json` owns ordered subjects, exclusions, commands, and owners across all governed gates.
15. **Pin the complete environment.** Exact top-level versions without a hash-locked graph are not reproducible.
16. **Publish identity-bound evidence.** Envelopes bind candidate, policy, scope, manifest, command, ownership, indicators, ceilings, and findings; aggregation rejects mismatches or stale evidence.
17. **Make policy time explicit.** Analysis depends on code; the orchestrator supplies one validated `--policy-date`, and identical commit plus date must produce byte-identical evidence.
18. **Prove measurement liveness.** Empty subjects, missing tools, missing evidence, unhealthy baseline emission, and degenerate runs fail closed.
19. **Use one portable local command.** `make verify` matches portable PR gates in CI order; capability-bound exclusions are explicit, valid CI gates. Preserve Makefile LF and mode.

Detailed rationale and failure modes: [Hard-rule rationale](references/hard-rule-rationale.md).

## Decision Gates

| Need | Action |
|---|---|
| Add a noisy lint rule | Open a policy issue; choose block, fix, or ratchet before enabling it. |
| Adopt gates in a legacy project | Emit a stable-identity baseline; greenfield starts empty. |
| Gate has no runnable fixture | Add a fixture or remove the gate; an empty gate is a false guarantee. |
| Gate exists only locally | Wire it into CI or delete it. |
| CI gate is absent from `make verify` | Add it, or declare a reasoned capability-scoped exclusion. |
| PR exceeds 400 changed lines | Split it unless the PR records `size:exception` with a reason. |
| Dependency introduces a CVE | File an issue and link the shrink-only allowlist entry to it. |

## Execution Steps

0. Read [the asset adoption guide](assets/README.md), copy from `assets/`, preserve provenance, and edit only marked configuration blocks.
1. Inventory and reconcile gate scripts, CI steps, and `make verify`; observe every gate exiting `1` on a real violation.
2. Pin governing tools and the full environment exactly.
3. Wire each gate into CI and the set-level parity test.
4. Create or migrate stable-identity baselines with targets and target dates.
5. Add positive, negative, empty-subject, and unhealthy-run coverage for the gate mechanism.
6. Run gates in their fixed order, publish the bound report, and repair documentation drift in the same change.

## Output Contract

Return:
- Gate surface inventory: gate, file, failure exit code, owner, non-owner, ceiling, and baseline.
- Wiring and local/CI parity evidence.
- Exact tool and environment pins.
- Baseline changes with migration reason, target, date, and source issue.
- Candidate-, policy-, scope-, manifest-, and command-bound indicators and findings.
- Documentation or implementation drift repaired in the same change.

Evidence schema, indicators, determinism checklist, and cadence limits:
[Evidence and determinism contract](references/evidence-and-determinism.md).

## Assets

`assets/` is the executable reference implementation. Never reconstruct a gate from prose. The
complete destination map, adoption locks, commands, and scope limits live in
[the asset adoption guide](assets/README.md).

| Bundle | Key assets | Purpose |
|---|---|---|
| Orchestration | `assets/ci.yml`, `assets/Makefile` | Fixed CI/local gate order and parity. |
| Policy and evidence | `assets/quality-policy.json`, `assets/scripts/quality_policy.py`, `assets/scripts/quality_report.py` | Shared scope plus identity-bound envelopes. |
| Gates | `assets/scripts/check_*.py`, `assets/scripts/policy_time.py` | Fail-closed executable rules. |
| Adoption locks | `assets/cosmic-ray.toml`, `assets/security-images.*.json`, `assets/pyproject.fragment.toml` | Pinned mutation, scanner, and dependency inputs. |
| Contract tests | `assets/tests/test_ci_workflow.py`, `assets/tests/test_gate_smoke.py`, `assets/tests/test_gate_liveness.py`, `assets/tests/test_adoption_preflight.py`, `assets/tests/test_policy_time.py`, `assets/tests/test_quality_policy.py`, `assets/tests/test_quality_report_contract.py`, `assets/tests/fixtures/**` | Wiring, failure, liveness, policy, and evidence proof. |

Keep every `HARNESS-PROVENANCE` marker. Re-resolve action SHAs and scanner digests during an
explicit upgrade; do not replace them with floating references. The provenance consistency policy
is enforced by `tests/test_skill_contract.py`; strict JSON payloads and sentinel files are listed
with reasons in `tests/provenance-exemptions.json`.

Design origins and deliberate upstream divergences: [Origins and history](references/origins-and-history.md).
