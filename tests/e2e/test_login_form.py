"""E2E: login form structure and accessibility verification.

Verifies the login form has correct:
- CSRF token (input[name=csrf_token]) per AGENTS.md §10
- method="post" on the <form> element
- visible email input and accessible submit button

The rendered form is the magic-link form (``#magic-link-form`` posting
to ``/auth/magic/start``, issue #1005), which only renders when
``APAP_AUTH_ENABLE_MAGIC_LINK`` is true. The Google-OAuth-era form
(``action="/auth/google"``, password input, "Entrar con Gmail" link)
was removed by issue #728. With the flag off the page renders no form
at all, so form-contract tests skip with an explicit reason (issue
#1153).

Issue #206 partial scope: covers only the public form surface,
no OAuth secrets required.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page


def _skip_if_oauth_not_configured(page: Page, base_url: str) -> None:
    """Skip when /login returns 503 (OAuth not configured in dev)."""
    preflight = page.request.get(f"{base_url}/login")
    if preflight.status == 503:
        pytest.skip(
            "/login returns 503 (Google OAuth not configured); "
            "login form cannot be observed end-to-end."
        )


def _goto_rendered_login_form(page: Page, base_url: str) -> None:
    """Navigate to /login and skip unless a form actually renders.

    ``login.html`` contains exactly one form — the magic-link section —
    which renders only when ``APAP_AUTH_ENABLE_MAGIC_LINK`` is true
    (#1005). With the flag off the page renders no form at all, so the
    form-contract tests cannot run (issue #1153).
    """
    _skip_if_oauth_not_configured(page, base_url)
    page.goto(f"{base_url}/login")
    if page.locator("#magic-link-form").count() != 1:
        pytest.skip(
            "login page renders no form: APAP_AUTH_ENABLE_MAGIC_LINK is "
            "false and login.html's only form is the flag-gated magic-link "
            "section (issue #1005)."
        )


def test_login_form_has_csrf_token_input(page: Page, base_url: str) -> None:
    """The login form includes a csrf_token hidden input (AGENTS.md §10)."""
    _goto_rendered_login_form(page, base_url)

    csrf_input = page.locator("#magic-link-form input[name='csrf_token']")
    csrf_input.wait_for(state="attached")
    assert csrf_input.count() == 1, (
        "login form must have exactly one input[name=csrf_token]"
    )


def test_login_form_method_is_post(page: Page, base_url: str) -> None:
    """The login <form> uses method="post" (not GET)."""
    _goto_rendered_login_form(page, base_url)

    form = page.locator("#magic-link-form")
    assert form.get_attribute("method") == "post", (
        "the magic-link form must use method=post"
    )


def test_login_form_action_matches_enabled_flow(
    page: Page, base_url: str
) -> None:
    """The login form posts to the auth entry point of the enabled flow.

    The magic-link flow posts to ``/auth/magic/start`` (#1005). The
    Google-OAuth-era ``action="/auth/google"`` form no longer exists
    (#728); the old assertion could only ever observe the removed
    variant (issue #1153).
    """
    _goto_rendered_login_form(page, base_url)

    form = page.locator(
        "#magic-link-form[action='/auth/magic/start'][method='post']"
    )
    assert form.count() == 1, (
        "login form must be <form id='magic-link-form' "
        "action='/auth/magic/start' method='post'>"
    )


def test_login_form_has_visible_email_field(page: Page, base_url: str) -> None:
    """The login form has a visible, required email input.

    The magic-link flow authenticates by emailed link, so there is no
    password input; the password assertion pinned the removed OAuth-era
    form (issues #728, #1005, #1153).
    """
    _goto_rendered_login_form(page, base_url)

    email_field = page.locator(
        "#magic-link-form input[type='email'][name='email'][required]"
    )
    assert email_field.count() == 1, (
        "the magic-link form must have one required input[type=email][name=email]"
    )
    email_field.wait_for(state="visible")


def test_login_form_submit_button_is_accessible(page: Page, base_url: str) -> None:
    """The login form submit button has an accessible name."""
    _goto_rendered_login_form(page, base_url)

    submit = page.locator('#magic-link-form button[type="submit"]')
    assert submit.count() >= 1, "login form must have a submit button"


def test_login_page_title_is_not_empty(page: Page, base_url: str) -> None:
    """/login renders a non-empty <title> element."""
    _skip_if_oauth_not_configured(page, base_url)
    page.goto(f"{base_url}/login")

    title = page.locator("title")
    title_text = title.inner_text()
    assert title_text.strip(), "/login page must have a non-empty <title>"
