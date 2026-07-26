"""Compliant fixture: has queries.py AND has _*_SQL constant in service.py.

Rule §22-compliant module with the proper query/service seam.
"""
_LIST_SQL = "SELECT id, name FROM sample WHERE activo = true"
