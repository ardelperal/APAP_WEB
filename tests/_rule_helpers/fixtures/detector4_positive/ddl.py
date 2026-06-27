"""Positive fixture for Detector 4 (hardcoded_role_check_in_ddl).

A string literal that hardcodes the role list inside a CHECK constraint.
Detector 4 must flag this — Rule 4 says derive from the Rol enum.
"""


DDL_WITH_HARDCODED_ROLES = """
CREATE TABLE foo (
    id UUID PRIMARY KEY,
    rol TEXT NOT NULL CHECK (rol IN ('developer', 'admin', 'key_user', 'reader'))
)
"""
