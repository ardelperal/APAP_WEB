# Origins and history

The harness combines role segregation and fixed engineering ceilings from upstream agent practice
with fail-closed mechanisms proven in a live Python codebase. This history explains intentional
choices; it is not required for routine execution.

## Upstream influences

- [`unclebob/swarm-forge`](https://github.com/unclebob/swarm-forge) supplied role-segregated agent
  harness concepts and the engineering, cleaner, architect, hardener, and QA policies behind rules
  11–14. Its tmux, Babashka, and worktree orchestration is not imported.
- [`ardelperal/APAP_WEB`](https://github.com/ardelperal/APAP_WEB) supplied the mutation degenerate-run
  guard, acquisition grace for modules awaiting measurement, and `--emit-baseline`. Issues #380,
  #381, #393, #424, #428, #431, #434, #436, #437, #441, #442, and #443 form the original
  antipattern catalog.

## Deliberate divergence

`swarm-forge` requires the latest governing tools and rejects cached or vendored copies. This
harness pins exact versions instead. Upstream optimizes for freshness; this harness optimizes for
reproducible verdicts. Do not replace exact pins with floating versions without changing the stated
goal of the harness.

## Why local/CI parity became a hard rule

APAP_WEB issue #504 and PR #505 exposed a structural blind spot: CI ran seventeen gates while the
documented local command ran four. Per-gate wiring assertions stayed green because they only asked
whether known gates appeared in CI; no test compared the complete CI set with the local set. This
harness initially had the same omission. Rule 19 and the set-level parity test exist because two
independent implementations reproduced the same defect.

## Comparative audit snapshot

The 2026-08-08 audit found this harness stricter than the then-current APAP_WEB configuration in
four areas: SHA-pinned actions and fixed runner labels, exact governing-tool pins beyond Ruff,
ratchet target dates, and aggregated indicators. APAP_WEB added its local parity command on
2026-08-10. Treat dated comparisons as historical evidence, not permanent claims about upstream.
