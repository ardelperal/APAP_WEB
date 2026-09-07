"""A NEW non-baselined module using annotated assignment for SQL constants.

Module name 'annassignmodule' is NOT in BASELINE_NO_QUERIES_MODULES, so it
should produce a CRITICAL query_seam_violation. This fixture exists to
guard against a regression where the detector only matches ast.Assign and
misses ast.AnnAssign (e.g. `_FOO_SQL: str = "..."`).
"""

ANNOTATED_SQL: str = "SELECT id FROM foo WHERE active = true"

