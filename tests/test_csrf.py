"""Shape and exemption atoms for the CSRF layer (M3.4 magic-link, issue #651).

The CSRF layer (``app/core.csrf``) carries its own surface constants
that need pin tests:

- ``CSRF_EXEMPT_PATHS`` — the magic-link endpoints
  (``/auth/magic/start``, ``/auth/magic/verify``) bypass CSRF because
  the token in the email link IS the authorization, not the session
  cookie. The auth layer already whitelists both paths in
  ``PUBLIC_PATHS`` (PR #854, commit ``5e95853``); the CSRF layer
  must mirror that exception. The exemption is bounded to these two
  exact paths — no prefix matching — so the rest of the
  defense-in-depth surface (same-site cookies, signed sessions,
  ``hmac.compare_digest``) stays intact for every other
  state-changing route.

The shape pin mirrors ``tests/test_public_paths.py``'s
``EXPECTED_PUBLIC_PATHS`` invariant: a refactor that drops an entry
(or adds a stray one) fails the atom immediately so the regression
surfaces here, not at the operator's ``/login`` screen.

The behavioural pin issues two httpx calls — one POST to
``/auth/magic/start`` with a valid body and NO csrf token, plus a
GET to ``/auth/magic/verify?token=x`` — and asserts the responses
are NOT 403. The exemption is at the CSRF-middleware layer, so the
assertion holds regardless of how the magic-link route itself would
have responded (200 for the start happy-path, 302 for the verify
happy-path). The cookie jar is empty: the magic-link flow is the
path TO a session, not one that requires one.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

import httpx
import pytest

from app.core.config import get_settings
from app.core.csrf import CSRF_EXEMPT_PATHS
from app.main import app

# Verified canonical set per PR #854 + PR #855 follow-up. Keep this
# in sync with ``PUBLIC_PATHS`` in ``tests/test_public_paths.py`` — the
# auth gate and the CSRF gate must agree on the magic-link exemption.
EXPECTED_CSRF_EXEMPT_PATHS: frozenset[str] = frozenset(
    {
        "/auth/magic/start",
        "/auth/magic/verify",
    }
)


# --- shape invariants -----------------------------------------------------


def test_csrf_exempt_paths_has_exactly_two_entries() -> None:
    """``CSRF_EXEMPT_PATHS`` matches the verified canonical set.

    Defense-in-depth: the middleware consults the constant on every
    non-safe request (see ``CsrfMiddleware.dispatch``). The atom
    asserts the on-disk frozenset equals exactly the two entries the
    spec pins — a typo or a refactor that drops the magic-link
    exemption would 403 the passwordless login flow and surface here.
    """
    assert CSRF_EXEMPT_PATHS == EXPECTED_CSRF_EXEMPT_PATHS, (
        f"CSRF_EXEMPT_PATHS drifted from the verified set; "
        f"got {sorted(CSRF_EXEMPT_PATHS)!r}, "
        f"expected {sorted(EXPECTED_CSRF_EXEMPT_PATHS)!r}. "
        f"The auth layer already whitelists both magic-link paths in "
        f"PUBLIC_PATHS (PR #854) — keep CSRF_EXEMPT_PATHS in lockstep."
    )
    assert len(CSRF_EXEMPT_PATHS) == 2, (
        f"CSRF_EXEMPT_PATHS must have exactly 2 entries "
        f"(/auth/magic/start and /auth/magic/verify); "
        f"got {len(CSRF_EXEMPT_PATHS)}"
    )


# --- behavioural pin: exemptions hold at the middleware layer ----------


@dataclass
class _MagicLinkPortSpy:
    """In-memory port stub.

    Records every ``create_token`` / ``consume_token`` call and
    hands back an opaque token. The exemption atom doesn't care
    about the persistence semantics — only that the route runs
    far enough to return its handler-level status code.
    """

    created: list[str] = field(default_factory=list)
    consumed: list[str] = field(default_factory=list)

    def create_token(self, email: str) -> str:
        _ = email  # signature parity with MagicLinkPort
        self.created.append(email)
        return "opaque-magic-token-for-exemption-atom"

    def consume_token(self, raw_token: str) -> str | None:
        self.consumed.append(raw_token)
        return None  # unknown token → 302 to /login


@dataclass
class _MailTransportSpy:
    """No-op transport stub that records ``send`` calls."""

    sent: list[dict[str, str]] = field(default_factory=list)

    def send(self, *, to_addr: str, subject: str, body: str) -> bool:
        self.sent.append({"to_addr": to_addr, "subject": subject, "body": body})
        return True


@pytest.fixture
def _wire_magic_link_state() -> Iterator[tuple[_MagicLinkPortSpy, _MailTransportSpy]]:
    """Wire the four ``app.state`` attributes the magic-link router reads.

    The module-level ``app`` (from ``conftest``) does NOT run its
    lifespan in unit tests, so ``magic_link_port``, ``smtp_transport``,
    ``public_base_url`` and ``session_secret`` are absent. The
    integration tests stand the lifespan up against a real Postgres
    schema; for the exemption atom we only need the route to run
    past the CSRF gate, so stubs suffice.
    """
    port = _MagicLinkPortSpy()
    transport = _MailTransportSpy()
    app.state.magic_link_port = port
    app.state.smtp_transport = transport
    app.state.public_base_url = "https://apap.example"
    app.state.session_secret = get_settings().session_secret
    try:
        yield port, transport
    finally:
        for attr in (
            "magic_link_port",
            "smtp_transport",
            "public_base_url",
            "session_secret",
        ):
            app.state.__dict__.pop(attr, None)


@pytest.mark.asyncio
async def test_csrf_exempts_magic_link_endpoints(
    client: httpx.AsyncClient,
    _wire_magic_link_state: tuple[_MagicLinkPortSpy, _MailTransportSpy],
) -> None:
    """Both magic-link endpoints are reachable WITHOUT a CSRF token.

    The exemption is at the middleware layer: a POST to
    ``/auth/magic/start`` and a GET to ``/auth/magic/verify`` with
    NO session cookie and NO ``X-CSRFToken`` header / form field
    must NOT return ``403`` with a CSRF error. The exact downstream
    status is the route's contract (``200`` for start with a valid
    email, ``400`` for start with a missing/invalid email, ``302``
    for verify with an unknown token) — the atom only pins the
    CSRF-middleware layer's exemption.

    Anonymous client (no cookies): the magic-link flow is the path
    TO a session, not one that requires one. Pre-M3.4 the CSRF
    middleware would 403 every one of these calls because there is
    no session cookie from which to read a ``csrf_token``.
    """
    # --- POST /auth/magic/start with a valid email -----------------
    # The JSON body matches the route's ``payload: dict[str, object]``
    # signature; ``magic-link-form.js`` sends exactly this shape from
    # the /login page. The atom does NOT include ``csrf_token`` in the
    # body OR the ``X-CSRFToken`` header — that absence is the point.
    start_response = await client.post(
        "/auth/magic/start",
        json={"email": "ana@apap.example"},
        follow_redirects=False,
    )
    assert start_response.status_code != 403, (
        f"POST /auth/magic/start without CSRF token returned "
        f"{start_response.status_code}; the CSRF middleware must "
        f"exempt this path per CSRF_EXEMPT_PATHS. Body: "
        f"{start_response.text!r}"
    )
    body = start_response.text.lower()
    assert "csrf" not in body, (
        f"POST /auth/magic/start response leaked a CSRF error "
        f"despite CSRF_EXEMPT_PATHS exemption: {start_response.text!r}"
    )

    # --- GET /auth/magic/verify?token=x (bypasses CSRF by method,
    # but pinned here so the exemption is documented end-to-end) ---
    verify_response = await client.get(
        "/auth/magic/verify?token=x",
        follow_redirects=False,
    )
    assert verify_response.status_code != 403, (
        f"GET /auth/magic/verify returned {verify_response.status_code}; "
        f"the CSRF middleware must exempt this path per "
        f"CSRF_EXEMPT_PATHS. Body: {verify_response.text!r}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"email": "ana@apap.example"}, id="valid-email"),
        pytest.param({}, id="missing-email"),
        pytest.param({"email": "not-an-email"}, id="invalid-email-format"),
    ],
)
async def test_csrf_exempts_magic_start_for_any_json_body(
    client: httpx.AsyncClient,
    _wire_magic_link_state: tuple[_MagicLinkPortSpy, _MailTransportSpy],
    payload: dict[str, object],
) -> None:
    """The CSRF exemption holds regardless of the JSON body shape.

    Each parametrised body exercises a different code path inside
    ``start_magic_link`` (happy path, missing email → 400, invalid
    format → 400). The CSRF-middleware exemption must apply to all
    of them — the handler's own validation runs AFTER the CSRF
    check, so a 400/422 from the handler is acceptable but a 403
    from the middleware would surface here as a regression.

    The atom intentionally does NOT pin the exact status code: the
    downstream contract is the route's, not the CSRF layer's. Only
    the negative invariant — "the middleware does not block this
    path" — is in scope.
    """
    response = await client.post(
        "/auth/magic/start",
        json=payload,
        follow_redirects=False,
    )
    assert response.status_code != 403, (
        f"POST /auth/magic/start with payload {payload!r} returned "
        f"{response.status_code}; CSRF_EXEMPT_PATHS must keep the "
        f"middleware from blocking this path. Body: {response.text!r}"
    )
    assert "csrf" not in response.text.lower(), (
        f"POST /auth/magic/start with payload {payload!r} leaked a "
        f"CSRF error despite CSRF_EXEMPT_PATHS exemption: "
        f"{response.text!r}"
    )
