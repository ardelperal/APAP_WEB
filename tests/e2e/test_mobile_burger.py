"""Regression test for the base_mobile.html burger (slice B of issue #147).

The original base_mobile.html (before this slice) had a single
"Menú" link pointing to /casas-acogida — a foster-homes module, not a
menu. On real iPhone / Android the user tapped "Menú" expecting a
nav and got a list of houses. This test pins the burger-as-disclosure
behaviour so the regression can't come back.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page
import pytest


MOBILE_VIEWPORT = {"width": 375, "height": 667}
LAYOUT_TOLERANCE_PX = 4


def _skip_if_login_unavailable(page: Page, base_url: str) -> None:
    preflight = page.request.get(f"{base_url}/login")
    if preflight.status == 503:
        pytest.skip(
            "/login returns 503 (Google OAuth not configured); "
            "mobile burger test cannot be observed end-to-end."
        )


def test_mobile_burger_is_visible(page: Page, base_url: str) -> None:
    """On iPhone UA, the header burger must be visible at 375px."""
    _skip_if_login_unavailable(page, base_url)
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.set_extra_http_headers(
        {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
                "Mobile/15E148 Safari/604.1"
            )
        }
    )
    page.goto(f"{base_url}/login", wait_until="domcontentloaded")
    burger = page.locator("details#mobile-burger > summary")
    burger.wait_for(state="visible", timeout=5000)
    bbox = burger.bounding_box()
    assert bbox is not None
    assert bbox["width"] > 0 and bbox["height"] > 0
    assert bbox["x"] + bbox["width"] <= MOBILE_VIEWPORT["width"] + LAYOUT_TOLERANCE_PX


def test_mobile_burger_toggles_nav_disclosure(page: Page, base_url: str) -> None:
    """Clicking the burger expands a list of module links inline.

    Before this fix the "Menú" link went to /casas-acogida (a single
    module) so this test would fail. After the fix the burger is a
    <details>/<summary> disclosure that opens inline and shows every
    module link, exactly like the desktop burger in base.html.
    """
    _skip_if_login_unavailable(page, base_url)
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.set_extra_http_headers(
        {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
                "Mobile/15E148 Safari/604.1"
            )
        }
    )
    page.goto(f"{base_url}/login", wait_until="domcontentloaded")

    # Initial state: details is closed
    details = page.locator("details#mobile-burger")
    assert details.evaluate("el => el.open") is False, (
        "burger should start closed"
    )

    # Click the burger
    page.locator("details#mobile-burger > summary").click()
    page.wait_for_timeout(200)
    assert details.evaluate("el => el.open") is True, (
        "burger should open after click"
    )

    # Every module link is visible
    for href, expected in [
        ("/", "Inicio"),
        ("/animales", "Animales"),
        ("/entradas", "Entradas"),
        ("/casas-acogida", "Casas de acogida"),
        ("/acogidas", "Estancias de acogida"),
        ("/adopciones", "Adopciones"),
        ("/sanidad", "Actuaciones"),
        ("/voluntarios", "Voluntarios"),
    ]:
        link = page.locator(f"details#mobile-burger nav a[href='{href}']")
        assert link.count() == 1, f"link {href!r} not present in mobile burger"
        text = link.inner_text().strip()
        assert expected in text, f"link {href!r} has text {text!r}, expected {expected!r}"
        # It must be visible (not display:none)
        assert link.is_visible(), f"link {href!r} not visible in expanded burger"


def test_mobile_burger_no_longer_points_to_casas_acogida(
    page: Page, base_url: str
) -> None:
    """Regression sentinel for the original bug: the burger was a plain
    link to /casas-acogida instead of a disclosure.
    """
    _skip_if_login_unavailable(page, base_url)
    page.set_viewport_size(MOBILE_VIEWPORT)
    page.set_extra_http_headers(
        {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
                "Mobile/15E148 Safari/604.1"
            )
        }
    )
    page.goto(f"{base_url}/login", wait_until="domcontentloaded")

    # The bug-bug: the original "Menú" link was a <a href="/casas-acogida">.
    # After the fix it's a <details> with a <summary> that doesn't navigate.
    bad_link_count = page.locator(
        "header a[href='/casas-acogida']:not([aria-label])"
    ).count()
    # After the fix, the only casa-acogida link is INSIDE the burger
    # disclosure (which is a <details> > <a>). So count = 1 (inside burger).
    # The OLD bug had it as a direct <a> in the header (outside any disclosure).
    # We assert the burger element exists, which proves the structure
    # changed from <a> to <details><summary>.
    assert page.locator("details#mobile-burger").count() == 1, (
        "mobile-burger <details> should be present in the header"
    )
    # And there's no direct header link to /casas-acogida
    direct_link = page.locator(
        "header > div > a[href='/casas-acogida']"
    )
    assert direct_link.count() == 0, (
        f"no direct link to /casas-acogida should be in the header anymore "
        f"(got {direct_link.count()})"
    )
    # The casa-acogida link still exists INSIDE the burger disclosure
    casa_in_burger = page.locator(
        "details#mobile-burger nav a[href='/casas-acogida']"
    )
    assert casa_in_burger.count() == 1, (
        "casa-acogida link should still be inside the burger disclosure"
    )


__all__ = [
    "test_mobile_burger_is_visible",
    "test_mobile_burger_toggles_nav_disclosure",
    "test_mobile_burger_no_longer_points_to_casas_acogida",
]
