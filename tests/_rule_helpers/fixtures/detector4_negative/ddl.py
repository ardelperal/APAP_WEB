"""Negative fixture for Detector 4 (rule 4 partial DDL marker).

A DDL string that does NOT contain the marker substring Detector 4 looks
for. Application-level validation handles role checks (rule 4); the
DDL literal must not duplicate the role list. Detector 4 must NOT
flag this fixture.
"""


DDL_WITHOUT_ROLE_CHECK = """
CREATE TABLE foo (
    id UUID PRIMARY KEY,
    rol TEXT NOT NULL
)
"""
