"""Regression: the rendered login page emits no inline ``style`` attribute.

Production battery evidence (issue #1152, deployed revision ``2d5024a``):
``style-src 'self'`` (``SecurityHeadersMiddleware._CSP_BASELINE``) blocks
the inline style attribute of the Lucide nav sprite
(``style="display:none"`` in ``app/templates/_lucide_nav_sprite.html``),
which ``base.html`` / ``base_mobile.html`` include on every page. The
browser reports the violation with hash
``sha256-aqNNdDLnnrDOnTNdkJpYlAxKVJtLt9CtFLklmInuUAE=`` — exactly
``sha256("display:none")`` — and the battery captured it on the
magic-link variant of ``/login`` (the sprite renders on every page
extending the base templates; the battery just observed it there).

The fix removes the inline attribute entirely (Tailwind ``hidden``
class, already compiled into ``/static/css/output.css``); the CSP
baseline stays untouched. These tests pin that contract without a
browser: an HTTP-level render of ``/login`` (OAuth env stubbed, the
same pattern ``tests/test_pages.py`` uses) asserting the HTML carries
no ``style=`` attribute at all, that the magic-link variant is
exercised, and that the CSP header is unchanged.
"""

from __future__ import annotations

import httpx
import pytest

BASELINE_CSP = (
    "default-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "img-src 'self' data:; "
    "style-src 'self'; "
    "script-src 'self'"
)


@pytest.fixture
async def login_response(client: httpx.AsyncClient, monkeypatch) -> httpx.Response:  # type: ignore[no-untyped-def]
    """Render ``/login`` with OAuth stubbed (the ``test_pages.py`` pattern).

    ``/login`` returns 503 when Google OAuth is not configured; stubbing
    both client id/secret makes the route render ``login.html``. The
    conftest sets ``APAP_AUTH_ENABLE_MAGIC_LINK=true``, so the magic-link
    section the battery flagged renders too.
    """
    monkeypatch.setenv("APAP_GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("APAP_GOOGLE_CLIENT_SECRET", "test-client-secret")
    return (await client.get("/login")).raise_for_status()


def test_login_renders_magic_link_variant(login_response: httpx.Response) -> None:
    """The rendered page IS the magic-link variant the battery flagged."""
    assert 'id="magic-link-form"' in login_response.text, (
        "the magic-link section did not render: the test would not "
        "exercise the variant the production battery flagged"
    )
    assert "/static/js/magic-link-form.js" in login_response.text


def test_login_emits_no_inline_style_attributes(login_response: httpx.Response) -> None:
    """No ``style=`` attribute may reach the browser (issue #1152).

    ``style-src 'self'`` rejects every inline style attribute; the fix
    removes the sprite's ``style="display:none"`` in favour of the
    Tailwind ``hidden`` class. Asserting the absence of ANY ``style=``
    attribute keeps the page future-proof against reintroductions.
    """
    assert 'style="' not in login_response.text, (
        "login.html rendered an inline style attribute: under "
        "style-src 'self' the browser blocks it (issue #1152)"
    )


def test_login_sprite_hidden_via_css_class(login_response: httpx.Response) -> None:
    """The Lucide sprite renders with the compiled ``hidden`` class."""
    sprite_open_tag = (
        '<svg xmlns="http://www.w3.org/2000/svg" class="hidden" '
        'aria-hidden="true">'
    )
    assert sprite_open_tag in login_response.text, (
        "the Lucide nav sprite is no longer hidden via the compiled "
        ".hidden class — the icons may flash unstyled on page load"
    )


def test_login_csp_header_stays_at_baseline(login_response: httpx.Response) -> None:
    """The fix must not relax the CSP baseline (issue #1152 criterion b)."""
    csp = login_response.headers.get("content-security-policy") or ""
    assert csp == BASELINE_CSP, (
        f"CSP header drifted from the baseline: got {csp!r}; the fix for "
        "issue #1152 removes the inline style, it does not touch style-src"
    )
