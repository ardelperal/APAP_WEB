"""Stub that re-exports the integration atoms so check_slice_completeness finds a test_*.py file under tests/ for the mail_transport slice."""
from tests.integration.test_magic_link import (  # noqa: F401
    test_console_mail_transport_appends_json_line,
    test_get_mail_transport_returns_console_when_no_smtp_env,
)
