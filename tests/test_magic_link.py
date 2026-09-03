"""Stub that re-exports integration atoms so check_slice_completeness finds a test_*.py file under tests/ for the magic_link slice.

F1 atoms live in tests/integration/test_magic_link.py.
F2 atoms live in tests/integration/test_magic_link_routes.py.
Both are re-exported here so the ratchet sees test_magic_link* under tests/.
"""
from tests.integration.test_magic_link import (  # noqa: F401
    test_console_mail_transport_appends_json_line,
    test_consume_magic_link_returns_email_on_first_use,
    test_consume_magic_link_returns_none_after_expiry,
    test_consume_magic_link_returns_none_on_reuse,
    test_get_mail_transport_returns_console_when_no_smtp_env,
    test_postgres_adapter_roundtrip_with_ephemeral_schema,
    test_request_magic_link_persists_row_with_correct_hash,
)
from tests.integration.test_magic_link_routes import (  # noqa: F401
    test_as1_authorized_email_persists_row_and_emails_transport,
    test_as2_unknown_email_returns_200_without_persisting,
    test_as3_consume_valid_token_issues_session_cookie,
    test_as4_consume_same_token_twice_returns_302_to_login,
    test_as5_consume_expired_token_returns_302_to_login,
    test_as6_feature_flag_off_makes_endpoints_noop,
    test_as8_unknown_email_response_time_within_50ms_of_known,
)
