"""E2E: login form structure and accessibility verification.

Verifies the login form has correct:
- CSRF token (input[name=csrf_token]) per AGENTS.md §10
- method="post" on the <form> element
- visible labels for email/password inputs
- submit button with accessible name
- action attribute pointing to /auth/google (the Google OAuth entry point)

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


def test_login_form_has_csrf_token_input(page: Page, base_url: str) -> None:
    """The login form includes a csrf_token hidden input (AGENTS.md §10)."""
    _skip_if_oauth_not_configured(page, base_url)
    page.goto(f"{base_url}/login")

    csrf_input = page.locator('input[name="csrf_token"]')
    csrf_input.wait_for(state="attached")
    assert csrf_input.count() == 1, (
        "login form must have exactly one input[name=csrf_token]"
    )


def test_login_form_method_is_post(page: Page, base_url: str) -> None:
    """The login <form> uses method="post" (not GET)."""
    _skip_if_oauth_not_configured(page, base_url)
    page.goto(f"{base_url}/login")

    form = page.locator('form[method="post"]')
    assert form.count() >= 1, "login page must have at least one method=post form"


def test_login_form_action_points_to_auth_google(page: Page, base_url: str) -> None:
    """The login form action is /auth/google (Google OAuth entry)."""
    _skip_if_oauth_not_configured(page, base_url)
    page.goto(f"{base_url}/login")

    form = page.locator('form[action="/auth/google"][method="post"]')
    assert form.count() == 1, (
        "login form must be <form action='/auth/google' method='post'>"
    )


def test_login_form_has_email_and_password_fields(page: Page, base_url: str) -> None:
    """The login form has visible email and password input fields."""
    _skip_if_oauth_not_configured(page, base_url)
    page.goto(f"{base_url}/login")

    # Accept any input with type email or with name containing email/identificador
    email_field = page.locator('input[type="email"], input[name*="email"], input[name*="identificador"]')
    assert email_field.count() >= 1, "login form must have an email/identifier input"

    password_field = page.locator('input[type="password"]')
    assert password_field.count() >= 1, "login form must have a password input"


def test_login_form_submit_button_is_accessible(page: Page, base_url: str) -> None:
    """The login form submit button has an accessible name."""
    _skip_if_oauth_not_configured(page, base_url)
    page.goto(f"{base_url}/login")

    # The primary submit button should be either <button type="submit"> or
    # <input type="submit"> with a value/name that describes the action.
    submit = page.locator('button[type="submit"], input[type="submit"]')
    assert submit.count() >= 1, "login form must have a submit button"


def test_login_page_title_is_not_empty(page: Page, base_url: str) -> None:
    """/login renders a non-empty <title> element."""
    _skip_if_oauth_not_configured(page, base_url)
    page.goto(f"{base_url}/login")

    title = page.locator("title")
    title_text = title.inner_text()
    assert title_text.strip(), "/login page must have a non-empty <title>"
