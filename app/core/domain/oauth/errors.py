"""Protocol-level error hierarchy for the OAuth flow.

The use cases in :mod:`app.core.application.oauth` raise these types
(not transport errors) so the route layer can translate each to a
single HTTP response. This is the §32.P4 fix for the legacy
``app.core.auth_flow`` which caught a bare ``InsForgeError`` and
silently turned every transport failure into ``/redirect(/login)``
— the new shape names the failure so a future handler can render
an error page instead of bouncing the user.

Three errors are defined:

- :class:`OAuthNotConfiguredError` — 503; the operator must set
  ``APAP_GOOGLE_CLIENT_ID`` / ``APAP_GOOGLE_CLIENT_SECRET``.
- :class:`CallbackInvalidError` — redirect to ``/login``; the
  callback arrived with neither an ``insforge_code`` nor a legacy
  ``code`` query parameter.
- :class:`UserNotAuthorizedError` — redirect to ``/unauthorized``;
  the email returned by InsForge did not resolve to an active row
  in ``usuarios_autorizados``.

The base :class:`OAuthError` is the umbrella type for an ``except``
clause that wants to handle any OAuth-flow failure uniformly (the
adapter's transport-error translation path uses it).
"""
from __future__ import annotations


class OAuthError(Exception):
    """Base class for all OAuth-flow domain errors.

    Subclasses are raised by the use cases in
    :mod:`app.core.application.oauth` and translated by the route
    layer into the appropriate HTTP response (redirect, 503, or 401).
    Adapter errors are translated to these Protocol-level types before
    they reach the use case — the application layer never sees a
    transport-level exception.
    """


class OAuthNotConfiguredError(OAuthError):
    """Raised when Google OAuth is not configured for this environment.

    The application layer raises this when the ``google_client_id`` /
    ``google_client_secret`` settings are empty. The route layer
    translates it to a ``503 Service Unavailable`` JSON response so
    the operator sees a clear "configure your env" message instead of
    a stack trace.

    The constructor takes no arguments: the message is fixed because
    the operator's remediation is the same regardless of which env
    var is missing (set both).
    """

    def __init__(self) -> None:
        super().__init__(
            "Google OAuth no está configurado: define "
            "APAP_GOOGLE_CLIENT_ID y APAP_GOOGLE_CLIENT_SECRET."
        )


class CallbackInvalidError(OAuthError):
    """Raised when the callback request lacks a usable OAuth code.

    The use case raises this when the callback arrives with neither
    an ``insforge_code`` nor a legacy ``code`` query parameter. The
    route layer redirects to ``/login`` (the same shape the legacy
    ``app.core.auth_flow`` used for the 165-line ``except
    InsForgeError`` bucket, but now applied ONLY to the genuinely
    invalid-input case — transport failures are translated
    separately, §32.P4).
    """

    def __init__(self, message: str = "no OAuth code provided") -> None:
        super().__init__(message)


class UserNotAuthorizedError(OAuthError):
    """Raised when the OAuth-returned email is not in ``usuarios_autorizados``.

    The use case raises this when the email returned by InsForge
    does not resolve to an active row in ``usuarios_autorizados``.
    The route layer redirects to ``/unauthorized`` and clears the
    short-lived ``apap_pkce`` cookie so the browser does not replay
    the bad verifier.

    Attributes:
        email: The email that was rejected. Carried as an attribute
            (NOT a log payload — log_safe redacts ``email`` from the
            closed 12-field list, so it is safe to log) so the
            adapter / route layer can include it in audit events
            without parsing the exception message.
    """

    def __init__(self, email: str) -> None:
        super().__init__(f"email not authorized: {email!r}")
        self.email = email


__all__ = [
    "CallbackInvalidError",
    "OAuthError",
    "OAuthNotConfiguredError",
    "UserNotAuthorizedError",
]
