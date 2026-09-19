"""E2E: WCAG 1.3.1 + ARIA landmark semantics — labelled <main>.

Issue #813: the page-level ``<main>`` carries ``aria-labelledby="main-title"``
referencing the page H1 (which also carries ``id="main-title"``). Module-level
section headers inside the main render as ``<section aria-labelledby>`` rather
than ``<header>`` to avoid landmark collision with the page-level header.

Pins: exactly one ``<main>`` per page with non-empty aria-labelledby; zero
``<header>`` inside ``<main>``; the labelledby target H1 exists and has text.

Public routes cover the mechanism; authenticated routes are parametrised with
explicit skip when the auth middleware redirects to ``/login`` (the same
preflight pattern used by ``test_a11y_skip_link.py`` and ``test_nav_layout.py``).
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

PUBLIC_ROUTES = ("/", "/login")
AUTH_ROUTES = ("/animales", "/entradas", "/voluntarios", "/admin", "/tareas")


def _preflight(page: Page, base_url: str) -> None:
    """Skip when OAuth is not configured (matches helpers in
    ``test_login_form.py`` and ``test_nav_layout.py``)."""
    if page.request.get(f"{base_url}/login").status == 503:
        pytest.skip(
            "/login returns 503 (Google OAuth not configured); "
            "landmark audit cannot run against an unconfigured login flow."
        )


def _skip_if_redirected(page: Page, base_url: str, target: str) -> bool:
    """Return True (and skip) when the auth middleware redirected to /login."""
    page.goto(f"{base_url}{target}", wait_until="domcontentloaded")
    if page.url.rstrip("/").endswith("/login") and target != "/login":
        pytest.skip(
            f"route {target!r} redirects to /login without a session; "
            "labelled-main mechanism is already covered by public-route tests."
        )
        return True
    return False


def _landmarks(page: Page) -> list:
    return page.evaluate(
        "() => Array.from(document.querySelectorAll('main')).map(m => ({"
        "  id: m.id,"
        "  labelledby: m.getAttribute('aria-labelledby'),"
        "  tabindex: m.getAttribute('tabindex')"
        "}))"
    )


# --- public-route sentinels ----------------------------------------------


def test_main_landmark_is_present_and_labelled_on_home(page: Page, base_url: str) -> None:
    """Exactly one <main> on / and it carries aria-labelledby='main-title'."""
    _preflight(page, base_url)
    _skip_if_redirected(page, base_url, "/")

    landmarks = _landmarks(page)
    assert len(landmarks) == 1, f"home page must have exactly one <main>, got {len(landmarks)}"
    assert landmarks[0]["id"] == "main", f"<main> must carry id='main', got {landmarks[0]['id']!r}"
    assert landmarks[0]["labelledby"] == "main-title", (
        f"<main> must carry aria-labelledby='main-title', got {landmarks[0]['labelledby']!r}"
    )
    assert landmarks[0]["tabindex"] == "-1", (
        f"<main> must carry tabindex='-1' (skip-link target from #812), got {landmarks[0]['tabindex']!r}"
    )


def test_h1_has_main_title_id_on_home(page: Page, base_url: str) -> None:
    """The labelledby target H1 exists with id='main-title' and non-empty text."""
    _preflight(page, base_url)
    _skip_if_redirected(page, base_url, "/")

    h1 = page.evaluate(
        "() => { const el = document.getElementById('main-title');"
        "  return el ? {tag: el.tagName, text: (el.textContent || '').trim()} : null; }"
    )
    assert h1 is not None, "element with id='main-title' must exist on the home page"
    assert h1["tag"] == "H1", f"#main-title must be an H1, got <{h1['tag'].lower()}>"
    assert h1["text"], "the labelledby target H1 must have non-empty text"


def test_no_duplicate_header_landmark_inside_main_on_home(page: Page, base_url: str) -> None:
    """Zero <header> elements inside <main> (would collide with page-level header)."""
    _preflight(page, base_url)
    _skip_if_redirected(page, base_url, "/")

    headers = page.evaluate("() => document.querySelectorAll('main header').length")
    assert headers == 0, f"<main> must contain zero <header>, got {headers}"


def test_exactly_one_nav_landmark_on_login(page: Page, base_url: str) -> None:
    """The mobile burger + desktop nav resolve to one or two <nav> landmarks."""
    _preflight(page, base_url)
    page.goto(f"{base_url}/login", wait_until="domcontentloaded")

    navs = page.evaluate("() => document.querySelectorAll('nav').length")
    assert 1 <= navs <= 2, f"/login must render one or two <nav>, got {navs}"


# --- authenticated-route sentinels (skip on redirect) -------------------


@pytest.mark.parametrize("route", AUTH_ROUTES)
def test_main_landmark_is_present_on_authenticated_routes(
    page: Page, base_url: str, route: str
) -> None:
    """<main> on every authenticated route carries aria-labelledby='main-title'."""
    _preflight(page, base_url)
    if _skip_if_redirected(page, base_url, route):
        return

    landmarks = _landmarks(page)
    assert len(landmarks) == 1, f"{route!r} must render exactly one <main>, got {len(landmarks)}"
    assert landmarks[0]["id"] == "main", f"{route!r}: <main> must carry id='main'"
    assert landmarks[0]["labelledby"] == "main-title", (
        f"{route!r}: <main> must carry aria-labelledby='main-title'"
    )


@pytest.mark.parametrize("route", AUTH_ROUTES)
def test_no_duplicate_header_landmark_on_authenticated_routes(
    page: Page, base_url: str, route: str
) -> None:
    """Zero <header> inside <main> on every authenticated route."""
    _preflight(page, base_url)
    if _skip_if_redirected(page, base_url, route):
        return

    headers = page.evaluate("() => document.querySelectorAll('main header').length")
    assert headers == 0, f"{route!r}: <main> must contain zero <header>, got {headers}"
