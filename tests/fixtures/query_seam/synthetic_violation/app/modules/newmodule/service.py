"""Synthetic new module fixture: _*_SQL in service.py, no queries.py.

NOT in BASELINE_NO_QUERIES_MODULES — this represents a NEW module
added after the rule was established. It should trigger a CRITICAL
query_seam_violation because it violates §22 without grandfathering.
"""
_NEW_THING_SQL = "SELECT id FROM new_thing"
