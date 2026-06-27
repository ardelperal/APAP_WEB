"""Negative fixture for Detector 4 (hardcoded_role_check_in_ddl).

A DDL string that does NOT contain the marker substring `CHECK (rol IN (`
— Detector 4 must NOT flag this. Application-level validation handles role
checks (rule 4).
"""


DDL_WITHOUT_ROLE_CHECK = """
CREATE TABLE foo (
    id UUID PRIMARY KEY,
    rol TEXT NOT NULL
)
"""
