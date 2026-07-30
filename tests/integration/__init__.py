"""Integration tests that execute every exported query function from
``app/modules/*/queries.py`` against a real Postgres engine.

Issue #329: SQL is never executed against a real Postgres engine.
"""
