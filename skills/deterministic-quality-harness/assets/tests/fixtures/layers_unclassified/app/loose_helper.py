# HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — negative fixture, do not "fix"
"""A file that does not fit the <package>/<module>/<layer>/ layout.

The gate cannot place this into a (module, layer) pair. Before the fix it was skipped in
silence and the gate reported clean; on a real codebase with a different layout that meant
118 of 178 files were never checked while CI stayed green.
"""


def helper(value: int) -> int:
    return value * 2
