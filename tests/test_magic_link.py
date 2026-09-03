"""Stub that re-exports the integration atoms so check_slice_completeness finds a test_*.py file under tests/ for the magic_link slice."""
from tests.integration.test_magic_link import (  # noqa: F401
    test_console_mail_transport_appends_json_line,
    test_consume_magic_link_returns_email_on_first_use,
    test_consume_magic_link_returns_none_after_expiry,
    test_consume_magic_link_returns_none_on_reuse,
    test_get_mail_transport_returns_console_when_no_smtp_env,
    test_postgres_adapter_roundtrip_with_ephemeral_schema,
    test_request_magic_link_persists_row_with_correct_hash,
)
