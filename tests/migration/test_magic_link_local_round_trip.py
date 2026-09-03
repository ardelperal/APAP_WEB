"""AS10-equivalent atom for the F3 magic-link round-trip gate (M1).

The single atom below drives the F3 helper
:func:`tests.migration._local_backend_fixture.run_magic_link_local_round_trip`
directly and asserts it returns a PASS-shaped dict with the magic-link
check name. The atom is the test-side mirror of the gate's
:func:`migration.verify_fallback_ready.check_magic_link_local_round_trip`
helper — both consume the same spawn-and-verify plumbing so a
regression in the helper shows up in both call sites.

The helper spawns uvicorn on a free port with the F3 env
(``APAP_AUTH_ENABLE_MAGIC_LINK=true`` + ``APAP_APP_BASE_URL`` pointing
at the loopback), seeds a user via ``POST /_test/seed_user``, posts
to ``/auth/magic/start``, reads ``tests/mailbox.jsonl`` for the
verify URL, GETs it, and asserts the response sets the
``apap_session`` cookie.

Hard Rules honoured:

- **Rule 1 (fixture gate)**: the helper builds its own schema +
  mailbox; no pre-existing state shared across atoms (only this
  atom exists today).
- **Rule 2 (DI)**: the lifespan wires ``StubAuthPort`` /
  ``PostgresMagicLinkAdapter`` / ``ConsoleMailTransport`` into
  ``app.state``; the helper drives the route layer via real HTTP.
- **Rule 3 (cardinality)**: the helper asserts one mailbox line +
  one ``apap_session`` cookie; one missing piece is FAIL.
- **Rule 4 (no humo)**: assertions on values (status code, cookie
  name, mailbox keys), never absence-of-error.
- **Rule 5 (no real backend)**: a free-port uvicorn + an
  ``APAP_TEST_POSTGRES_DSN``-backed ephemeral schema. No real
  InsForge / no shared state.

Loud failure when Postgres is absent: the helper raises
:class:`RuntimeError` with a clear message naming
``APAP_TEST_POSTGRES_DSN``; the gate wrapper
(:func:`migration.verify_fallback_ready.check_magic_link_local_round_trip`)
catches that and converts it to a ``FAIL`` ``CheckResult``. The atom
below re-raises the ``RuntimeError`` so the test fails loudly when
Postgres is missing in CI (matches AGENTS.md integration-test policy).
"""

from __future__ import annotations

import pytest

from tests.migration._local_backend_fixture import run_magic_link_local_round_trip

pytestmark = pytest.mark.integration


def test_magic_link_local_round_trip_against_spawned_backend() -> None:
    """Drive the F3 helper; assert it returns a PASS-shaped dict.

    Spec AS7 / F3 atom. Spawns the local backend with the magic-link
    flag on, seeds a user, exercises the start / verify endpoints,
    and confirms the verify response carries ``apap_session``.

    The helper itself provisions an ephemeral Postgres schema and
    cleans it up in ``finally``; this atom only asserts the
    returned payload shape (matches the migration gate's contract
    that the helper returns a ``CheckResult``-shaped dict).
    """
    payload = run_magic_link_local_round_trip()

    assert payload["name"] == "magic_link_local_round_trip"
    assert payload["status"] == "PASS"
    assert isinstance(payload["evidence"], str)
    assert payload["evidence"]  # non-empty
