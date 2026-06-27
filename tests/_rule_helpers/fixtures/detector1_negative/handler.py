"""Negative fixture for Detector 1 (rule_uses_execute_sql).

A GET handler that calls client.execute_sql directly. Per spec REQ-1
scenario 2, GET handlers are intentionally exempt: a read handler may
delegate to a service that runs SQL.
"""


def handler_list_things(client):
    """GET route is allowed to read SQL."""
    return client.execute_sql("SELECT * FROM things", [])
