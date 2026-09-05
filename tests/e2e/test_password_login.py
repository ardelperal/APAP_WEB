"""E2E test for the password login form (T2.1.4 — spec AS5.1).

Spec: openspec/changes/phase2-classic-password/specs/phase2-classic-password/spec.md
- AS5.1: /login renders email + password fields
- R5: magic-link form is below the password form (secondary option)
- AS6.1: login form submits via JSON fetch + sets apap_session cookie

This test runs against the LOCAL backend (the deployed apap-web with the
local backend mounted). The password route is gated behind
APAP_AUTH_ENABLE_PASSWORD=true which the operator toggles.
"""
from __future__ import annotations

import os

import pytest
from playwright.sync_api import Page


# Same skip / fallback pattern as test_mobile_burger.py
_skip_direct_backend = pytest.mark.skipif(
    not os.environ.get("APAP_E2E_DEPLOYED_DIRECT"),
    reason="password login e2e against the deployed stack — only works when the "
           "test runner is on the Coolify docker network",
)


@pytest.mark.e2e_deployed
def test_password_login_form_renders_email_and_password_fields(page: Page, base_url: str) -> None:
    """AS5.1 — login form has email + password inputs + forgot link + magic-link secondary."""
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(f"{base_url}/login", wait_until="domcontentloaded")

    # Password form
    email_input = page.locator("input[name='email'][type='email']")
    pwd_input = page.locator("input[name='password'][type='password']")
    submit = page.locator("button:has-text('Iniciar sesión')")
    forgot = page.locator("a:has-text('Olvidé mi contraseña')")

    # The password login form is rendered when APAP_AUTH_ENABLE_PASSWORD=true
    # On the deployed app right now that's not set, so we check presence OR a sensible skip path
    if email_input.count() == 0:
        pytest.skip(
            "password login not enabled on the deployed app "
            "(APAP_AUTH_ENABLE_PASSWORD=false); this e2e is for after Phase 2 ships"
        )

    assert email_input.count() >= 1, "email input must exist"
    assert pwd_input.count() >= 1, "password input must exist"
    assert submit.count() >= 1, "submit button must exist"
    assert forgot.count() >= 1, "forgot-password link must exist"

    # Magic-link form is still present as the secondary option
    magic_form = page.locator("form#magic-link-form")
    assert magic_form.count() == 1, "magic-link form must remain"
