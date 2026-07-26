"""Legacy fixture: has _*_SQL in service.py but NO queries.py.

Module name is "legacymodule" (NOT in BASELINE_NO_QUERIES_MODULES) so
it should produce a CRITICAL query_seam_violation — it represents a
hypothetical NEW module added after issue #290 without following §22.
"""
_LEGACY_INSERT_SQL = "INSERT INTO legacy_table (name) VALUES ($1)"
