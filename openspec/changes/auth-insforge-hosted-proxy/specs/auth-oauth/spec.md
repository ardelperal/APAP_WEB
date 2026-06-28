# Capability Spec — APAP_WEB Auth via InsForge Hosted OAuth Proxy

## Purpose

Define the production OAuth contract between APAP_WEB and InsForge's
hosted OAuth proxy. InsForge now fronts Google (and other providers) with
a two-step flow: APAP starts the flow, the browser visits Google's
consent screen via InsForge's hosted proxy, and InsForge bounces the
browser back to the app's callback with an intermediate ``insforge_code``
that the app then exchanges via ``POST /api/auth/oauth/exchange``. The
legacy direct-callback shape (``?code=``) is kept only for tests and any
direct Google → app redirect.

## Requirements

### Requirement: Start OAuth via InsForge-hosted proxy

The system MUST start the Google OAuth flow by calling InsForge's
``GET /api/auth/oauth/google`` with the PKCE challenge and the
app's ``redirect_uri``.

#### Scenario: Start returns a Google OAuth URL

- GIVEN an unauthenticated user lands on ``/`` or clicks "Iniciar sesión"
- WHEN the app handles ``GET /login``
- THEN it calls InsForge with ``redirect_uri`` (the app's callback) and
  ``code_challenge`` (the SHA-256 of a fresh random ``code_verifier``)
- AND it stores the ``code_verifier`` in a short-lived ``apap_pkce``
  cookie (``HttpOnly; SameSite=Strict; Secure; Max-Age=600``)
- AND it redirects the browser to the ``authUrl`` InsForge returns

#### Scenario: PKCE verifier entropy

- GIVEN the app starts the flow
- WHEN it generates the ``code_verifier``
- THEN the verifier MUST be at least 43 random URL-safe characters
  (InsForge's API contract: ``code_challenge must be at least 43
  characters`` — a shorter verifier would make the hash untrustworthy)

### Requirement: Callback accepts the InsForge intermediate code

The system MUST accept ``insforge_code`` at ``/auth/callback`` and
exchange it via InsForge's ``POST /api/auth/oauth/exchange?client_type=web``.

#### Scenario: InsForge proxy callback

- GIVEN a user completes the Google consent screen
- WHEN InsForge redirects the browser to ``/auth/callback?insforge_code=<temporary>``
- THEN the handler MUST POST to ``/api/auth/oauth/exchange?client_type=web``
  with body ``{"code": insforge_code, "code_verifier": <original>}``
- AND on a 200 response, the handler MUST read ``accessToken`` (NOT
  ``token``) and ``user.email`` / ``user.id`` from the response body

#### Scenario: Legacy direct-callback still works

- GIVEN a test or a direct redirect from Google (pre-InsForge-proxy)
  hits ``/auth/callback?code=<google-code>``
- WHEN the handler receives the request
- THEN it MUST fall back to ``exchange_google_oauth_code`` against
  ``/api/auth/oauth/google/callback`` so existing flows and tests do
  not break

#### Scenario: PKCE cookie missing or tampered

- GIVEN the callback receives ``insforge_code`` (or ``code``) but the
  browser did NOT carry a valid ``apap_pkce`` cookie
- WHEN the handler validates the PKCE state
- THEN it MUST redirect to ``/login`` (NOT raise, NOT 500)
- AND the response MUST clear any stale ``apap_pkce`` cookie

#### Scenario: InsForge rejects the insforge_code

- GIVEN the callback posts to ``/api/auth/oauth/exchange``
- WHEN InsForge returns 401 ``INVALID_CREDENTIALS`` (code expired or wrong)
- THEN the handler MUST redirect to ``/login``
- AND MUST NOT issue a session cookie

### Requirement: Session issuance on successful exchange

After a successful InsForge exchange, the handler MUST look the email up
in ``usuarios_autorizados`` and either issue a signed session cookie
(authorized) or redirect to ``/unauthorized`` (email not in the allowlist).

#### Scenario: Authorized user

- GIVEN InsForge returns a user whose email IS in ``usuarios_autorizados``
  with ``activo=True``
- WHEN the handler completes the exchange
- THEN it MUST issue a signed session cookie carrying ``email``, ``rol``,
  ``user_id``, ``is_authorized=True``, and a fresh ``csrf_token``
  (≥32 chars)
- AND MUST redirect to ``/``
- AND MUST clear the short-lived ``apap_pkce`` cookie
- AND MUST emit a structured ``auth.login`` log event with the user_id
  (email field is REDACTED by the closed 12-field redaction list)

#### Scenario: Unauthorized email

- GIVEN InsForge returns a user whose email is NOT in ``usuarios_autorizados``
- WHEN the handler completes the exchange
- THEN it MUST redirect to ``/unauthorized`` (do NOT issue a session cookie)

### Requirement: CSRF token in session

The session payload MUST carry a CSRF token so the CSRF middleware can
validate state-changing requests without relying solely on SameSite cookies.

#### Scenario: Session shape

- GIVEN the handler issues a session cookie after a successful exchange
- WHEN the cookie is decoded
- THEN the payload MUST contain a ``csrf_token`` key
- AND the token MUST be at least 32 characters of random URL-safe data
