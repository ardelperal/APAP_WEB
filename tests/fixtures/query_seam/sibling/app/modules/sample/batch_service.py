"""Sibling fixture: has batch_service.py with SQL, NOT service.py.

The detector only checks service.py. batch_service.py is an intra-module
sibling and is not subject to the §22 seam rule.
"""
_SAMPLE_BATCH_SQL = "SELECT id, name FROM sample"
