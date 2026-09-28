"""Browser binding for the magic-link state (issue #1004 round-1 fix).

The login-CSRF fix binds the emailed verify URL to the initiating
browser: ``POST /auth/magic/start`` set-cookies ``apap_magic_state``
in the browser that requested the link, and
``GET /auth/magic/verify`` demands that cookie to equal the URL
``state`` (timing-safe comparison) BEFORE consuming the token.

Why a cookie: the emailed URL carries both secrets (token and state),
so the URL alone is still a bearer capability. The cookie is what
makes it non-forwardable — cookies are only set by responses to
requests the browser itself made, so an attacker cannot plant the
binding in the victim's browser and the forwarded full URL fails
closed there. ACCEPTED LIMITATION (operator decision, issue #1004):
the link is NOT portable across devices — a user who requests the
link on one device and opens it on another gets the fail-closed
redirect and must re-request the link from the target device.

The helpers live beside the magic-link router (same package, one
focused write thread with issue #1004) so the router stays within its
50-line handler budget and its mutation-site ratchet.
"""
from __future__ import annotations

import hmac

from starlette.requests import Request
from starlette.responses import Response

MAGIC_STATE_COOKIE_NAME = "apap_magic_state"
"""Cookie binding the emailed state to the browser that requested the
link. Set by ``POST /auth/magic/start``, required (and expired) by
``GET /auth/magic/verify``."""

MAGIC_STATE_COOKIE_PATH = "/auth/magic"
"""Path scope of the state cookie: narrow to the magic-link routes so
it never rides on any other request."""


def state_cookie_matches(request: Request, url_state: str | None) -> bool:
    """Return ``True`` only when the browser's state cookie is present
    and equals the URL ``state`` (timing-safe comparison).

    This is the browser binding of the emailed URL: the attacker's
    forwarded full URL carries the state but not the victim's cookie,
    so the comparison fails in any browser other than the one that
    made the ``/auth/magic/start`` request. Missing either half fails
    closed WITHOUT consuming the server-side binding, so a user whose
    browser legitimately dropped the cookie still gets the no-oracle
    redirect and nothing else is burned.
    """
    cookie_state = request.cookies.get(MAGIC_STATE_COOKIE_NAME)
    if url_state is None or cookie_state is None:
        return False
    return hmac.compare_digest(url_state, cookie_state)


def set_state_cookie(response: Response, value: str, max_age: int) -> None:
    """Attach the ``apap_magic_state`` cookie to the start response.

    Flags: ``httponly`` (invisible to JS), ``secure`` (HTTPS only),
    ``samesite="lax"`` (survives the cross-site top-level redirect from
    the email client, same reasoning as the session cookie),
    ``path=MAGIC_STATE_COOKIE_PATH`` (scoped to the magic-link routes)
    and ``max_age`` = the state-binding TTL so the cookie and the
    server-side binding expire together. The cookie is set ONLY in the
    response to the browser that made the start request — this is what
    makes the emailed URL non-forwardable (issue #1004).
    """
    response.set_cookie(
        key=MAGIC_STATE_COOKIE_NAME,
        value=value,
        max_age=max_age,
        path=MAGIC_STATE_COOKIE_PATH,
        httponly=True,
        secure=True,
        samesite="lax",
    )


def expire_state_cookie(response: Response) -> None:
    """Expire the ``apap_magic_state`` cookie on a successful verify.

    ``delete_cookie`` emits ``Max-Age=0`` with the same Path scope, so
    the browser drops the binding as soon as the login completes and a
    spent state cookie cannot be replayed.
    """
    response.delete_cookie(key=MAGIC_STATE_COOKIE_NAME, path=MAGIC_STATE_COOKIE_PATH)
