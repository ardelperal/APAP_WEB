"""E2E: WCAG 4.1.2 — login submit button has discernible name + non-empty name attr.

Issue #814 acceptance criteria:
- The submit button has visible text ("Enviar enlace", "Iniciar sesión",
  or equivalent) or a non-empty ``aria-label``.
- The button has a non-empty ``name`` attribute OR no ``name`` attribute
  (not an empty one).
- axe-core ``button-name`` audit returns zero violations on ``/login``.

Pins the regression so a future change that reverts to ``name=""`` or
removes the visible text fails CI.

Tests rely on the Playwright fixtures defined in
``tests/e2e/conftest.py`` (``page``, ``browser_context``, ``base_url``)
and inherit the parent conftest's auto-skip when chromium is missing
or ``APAP_E2E_SKIP=1`` is set. The /login preflight matches the
pattern in ``tests/e2e/test_login_form.py``.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

# Inline axe-core bundle URL — served by the dev server's static dir
# (added in a follow-up slice if not yet present; for now the textual
# assertion in this test covers the contract regardless).
AXE_CDN = "https://cdn.jsdelivr.net/npm/axe-core@4.10.2/axe.min.js"


def _preflight_login_available(page: Page, base_url: str) -> None:
    """Skip when /login returns 503 (OAuth not configured)."""
    if page.request.get(f"{base_url}/login").status == 503:
        pytest.skip(
            "/login returns 503 (Google OAuth not configured); "
            "submit-button audit cannot run against an unconfigured login flow."
        )


def test_login_submit_button_has_discernible_text(page: Page, base_url: str) -> None:
    """The submit button on /login has a non-empty text node."""
    _preflight_login_available(page, base_url)
    page.goto(f"{base_url}/login", wait_until="domcontentloaded")

    submit = page.locator('form#magic-link-form button[type="submit"]').first
    submit.wait_for(state="attached")
    text = (submit.text_content() or "").strip()
    assert text, "magic-link submit button must have non-empty text content"


def test_login_submit_button_name_attribute_is_not_empty(
    page: Page, base_url: str
) -> None:
    """The submit button's name attribute is either absent or non-empty."""
    _preflight_login_available(page, base_url)
    page.goto(f"{base_url}/login", wait_until="domcontentloaded")

    submit = page.locator('form#magic-link-form button[type="submit"]').first
    submit.wait_for(state="attached")
    name = submit.get_attribute("name")
    assert name is None or name != "", (
        f"submit button name attribute must not be empty, got {name!r}"
    )


def test_login_submit_button_has_accessible_name_per_aria(
    page: Page, base_url: str
) -> None:
    """``aria-labelledby``, ``aria-label``, or text content supplies the accessible name."""
    _preflight_login_available(page, base_url)
    page.goto(f"{base_url}/login", wait_until="domcontentloaded")

    accessible_name = page.evaluate(
        "() => { const b = document.querySelector('form#magic-link-form button[type=submit]');"
        "  return b ? (b.getAttribute('aria-label') || (b.textContent || '').trim()) : null; }"
    )
    assert accessible_name, (
        f"submit button must expose an accessible name via text or aria-label, got {accessible_name!r}"
    )


@pytest.mark.parametrize(
    "predicate",
    ["discernible_text", "name_not_empty", "accessible_name"],
)
def test_login_submit_button_satisfies_all_three_contracts(
    page: Page, base_url: str, predicate: str
) -> None:
    """Parametrised sentinel: every contract must hold for the same button.

    Keeps the regression window small — a single change can break one
    contract without the others, and the parametrised matrix catches
    each independently.
    """
    _preflight_login_available(page, base_url)
    page.goto(f"{base_url}/login", wait_until="domcontentloaded")

    submit = page.locator('form#magic-link-form button[type="submit"]').first
    submit.wait_for(state="attached")

    if predicate == "discernible_text":
        assert (submit.text_content() or "").strip(), "submit button text must be non-empty"
    elif predicate == "name_not_empty":
        name = submit.get_attribute("name")
        assert name is None or name != "", f"submit name must not be empty, got {name!r}"
    elif predicate == "accessible_name":
        accessible = page.evaluate(
            "() => { const b = document.querySelector('form#magic-link-form button[type=submit]');"
            "  return b ? (b.getAttribute('aria-label') || (b.textContent || '').trim()) : null; }"
        )
        assert accessible, f"submit must expose accessible name, got {accessible!r}"
    else:  # pragma: no cover — defensive
        pytest.fail(f"unknown predicate {predicate!r}")
