"""Use case: clear the session cookie and prepare the logout response.

The use case has no domain logic — it returns the
:class:`ClearSessionParams` value object the route layer uses to
build the ``Set-Cookie`` that expires the session. The actual
cookie-clearing constants live in
:func:`app.core.session.clear_session_cookie_params` (the same
helper the legacy ``app.core.auth_flow`` route called); the use
case simply wraps that return value in a typed value object so
the application layer's contract is explicit.

Hexagonal contract:

- Inputs: none.
- Outputs: a :class:`ClearSessionParams` value object.
- Side effects: none.

The use case exists for symmetry with the other three
(``login_page``, ``start_google_login``, ``callback``) so every
``/login``-tree endpoint has a one-function-per-file representation
in the application package. The single-line delegation is
deliberate (see the slice-defining ``app.core.application.catalogos``
pattern): the route layer is the only place that touches
:class:`fastapi.responses.RedirectResponse`, and the use case
documents the "what does logout mean" without committing to a
specific HTTP shape.
"""


from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.session import clear_session_cookie_params


@dataclass(frozen=True, slots=True)
class ClearSessionParams:
    """The kwargs the route layer feeds to ``Response.set_cookie`` to expire the session.

    Mirrors the dict :func:`app.core.session.clear_session_cookie_params`
    returns. Wrapped in a frozen dataclass so the application
    layer's return type is explicit and the route layer does not
    have to know which session helper produced the parameters.

    The ``samesite="strict"`` field is the PR-5B (REQ-AH-5)
    default — even for the clearing cookie — so the browser can
    match the Set-Cookie against the original ``apap_session``
    cookie minted with the same ``samesite="strict"``. A future
    migration to ``Lax`` only needs to change this dataclass.

    Attributes:
        kwargs: The keyword arguments to pass to
            :meth:`fastapi.responses.Response.set_cookie`. The
            ``key`` is ``apap_session``, ``value=""``, ``max_age=0``,
            ``path="/"``, ``httponly=True``, ``secure=True``,
            ``samesite="strict"``.
    """

    kwargs: dict[str, Any]


def logout() -> ClearSessionParams:
    """Return the cookie-clearing parameters for the logout response.

    The legacy ``app.core.auth_flow::logout`` route did the same
    thing in two lines: ``response = _redirect("/")`` and
    ``response.set_cookie(**clear_session_cookie_params())``. This
    use case extracts the second line so the route layer becomes:

    .. code-block:: python

        @app.get("/logout")
        def logout() -> Response:
            response = _redirect("/")
            response.set_cookie(**logout_uc().kwargs)
            return response

    The dict return is the explicit
    :class:`ClearSessionParams` value object; the use case does
    not call ``Response`` directly because the application layer
    must stay transport-agnostic (rule §31).
    """
    return ClearSessionParams(kwargs=dict(clear_session_cookie_params()))


__all__ = ["ClearSessionParams", "logout"]
