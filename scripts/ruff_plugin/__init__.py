"""APAP ruff plugin package (Slice 1 of hardening-2026-q2, PR-1B).

Registers custom ruff rules APAP001 (active) and APAP003 (registered, gated
by Slice 6 to add it to the lint ``select``). See:

- ``openspec/changes/hardening-2026-q2/specs/01-dev-tooling-gate/spec.md``
- ``openspec/changes/hardening-2026-q2/tasks.md`` (T-1B.1, T-1B.2)
"""
