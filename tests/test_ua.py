"""Unit tests for ``app.core.ua.is_mobile``.

TDD slice A of the UA-based template selection (engram obs #15705).
The pure helper is the foundation the middleware builds on, so it
gets full coverage before we touch any wiring.

Tablet handling is intentional: iPad / Android tablets are NOT
mobile (v1 contract) — see ``app/core/ua.py`` docstring and the
``is_mobile`` docstring. A regression here would mis-route tablet
traffic to ``base_mobile.html`` and break layout.
"""

from __future__ import annotations

import pytest

from app.core.ua import is_mobile

# --- iPhone / iOS -----------------------------------------------------------


def test_is_mobile_returns_true_for_iphone() -> None:
    """An iPhone UA is mobile."""
    ua = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 "
        "Mobile/15E148 Safari/604.1"
    )
    assert is_mobile(ua) is True


def test_is_mobile_returns_true_for_iphone_safari() -> None:
    """The canonical iPhone Safari UA string is mobile.

    Exercises the ``Mobile`` branch and the ``iPhone`` branch
    simultaneously — both must fire, but ``True OR True == True``.
    """
    ua = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 "
        "Mobile/15E148 Safari/604.1"
    )
    assert is_mobile(ua) is True


def test_is_mobile_returns_true_for_ipod() -> None:
    """An iPod touch UA is mobile (legacy ``iPod`` branch)."""
    ua = "Mozilla/5.0 (iPod touch; CPU iPhone OS 12_0 like Mac OS X)"
    assert is_mobile(ua) is True


# --- Android ----------------------------------------------------------------


def test_is_mobile_returns_true_for_android_phone() -> None:
    """An Android *phone* UA (with ``Mobile`` substring) is mobile.

    Android tablets legitimately omit ``Mobile`` — covered by
    ``test_is_mobile_returns_false_for_android_tablet``.
    """
    ua = (
        "Mozilla/5.0 (Linux; Android 10; Pixel 4) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/91.0.4472.114 Mobile Safari/537.36"
    )
    assert is_mobile(ua) is True


def test_is_mobile_returns_true_for_chrome_android() -> None:
    """The canonical Chrome on Android UA (Pixel 4 + Mobile Safari)."""
    ua = (
        "Mozilla/5.0 (Linux; Android 10; Pixel 4) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/91.0.4472.114 Mobile Safari/537.36"
    )
    assert is_mobile(ua) is True


def test_is_mobile_returns_false_for_android_tablet() -> None:
    """Android tablets (no ``Mobile`` substring) are NOT mobile.

    Samsung Galaxy Tab S4 example. Tablets have the screen real
    estate for the desktop layout — the v1 contract treats them
    as desktop. If this starts returning ``True``, ``base_mobile.html``
    will be served to Galaxy Tab users: regression to flag.
    """
    ua = "Mozilla/5.0 (Linux; Android 9; SM-T720)"
    assert is_mobile(ua) is False


def test_is_mobile_returns_false_for_ipad() -> None:
    """An iPad UA is NOT mobile (tablet, not phone)."""
    ua = (
        "Mozilla/5.0 (iPad; CPU OS 13_2 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0 "
        "Mobile/15E148 Safari/604.1"
    )
    # iPad UAs frequently contain the literal substring ``Mobile``
    # (the iOS version string), so the dedicated iPad exclusion
    # pattern must take precedence here. If this regresses to True,
    # slice A's tablet rule is broken.
    assert is_mobile(ua) is False


def test_is_mobile_returns_false_for_kindle() -> None:
    """A Kindle (Amazon Silk / e-reader) UA is NOT mobile (tablet branch)."""
    ua = "Mozilla/5.0 (Linux; U; Android 4.4.3; en-us; KFASWI Build/KTU84M)"
    assert is_mobile(ua) is False


# --- Desktop ----------------------------------------------------------------


def test_is_mobile_returns_false_for_desktop_chrome() -> None:
    """A vanilla desktop Chrome UA is NOT mobile."""
    ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    assert is_mobile(ua) is False


def test_is_mobile_returns_false_for_desktop_firefox() -> None:
    """A vanilla desktop Firefox UA is NOT mobile."""
    ua = "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0"
    assert is_mobile(ua) is False


def test_is_mobile_returns_false_for_desktop_safari() -> None:
    """A macOS Safari UA is NOT mobile (no ``Mobile``/``iPhone``/etc.)."""
    ua = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
    )
    assert is_mobile(ua) is False


# --- Edge cases: missing / non-browser clients ------------------------------


def test_is_mobile_returns_false_for_none() -> None:
    """A ``None`` user-agent is treated as non-browser (False, not a crash).

    Defensive default — non-browser clients (curl, server-to-server
    scripts) send no UA. Defaulting to False keeps them on the
    desktop template, which is the safest path (no false positives).
    """
    assert is_mobile(None) is False  # type: ignore[arg-type]


def test_is_mobile_returns_false_for_empty_string() -> None:
    """An empty UA is treated as non-browser."""
    assert is_mobile("") is False


def test_is_mobile_returns_false_for_curl_user_agent() -> None:
    """A curl UA (typical script) is NOT mobile.

    curl sends ``User-Agent: curl/X.Y.Z`` which mentions none of
    the mobile patterns. Cross-check the helper behaves correctly
    for the most common scripted client.
    """
    ua = "curl/8.4.0"
    assert is_mobile(ua) is False


def test_is_mobile_returns_false_for_python_requests() -> None:
    """A Python ``requests`` library UA is NOT mobile."""
    ua = "python-requests/2.31.0"
    assert is_mobile(ua) is False


# --- Legacy / niche mobile clients ------------------------------------------


@pytest.mark.parametrize(
    "ua",
    [
        # BlackBerry (legacy)
        "Mozilla/5.0 (BlackBerry; U; BlackBerry 9900; en) AppleWebKit/534.11+ "
        "(KHTML, like Gecko) Version/7.1.0.346 Mobile Safari/534.11+",
        # Opera Mini
        "Opera/9.80 (Android; Opera Mini/36.2.2254/119.132; U; en) "
        "Presto/2.12.423 Version/12.16",
        # Windows Phone (legacy)
        "Mozilla/5.0 (compatible; MSIE 10.0; Windows Phone OS 8.0; "
        "Trident/6.0; IEMobile/10.0; ARM; Touch)",
        # webOS (legacy Palm)
        "Mozilla/5.0 (webOS/1.4.5; U; en-US) AppleWebKit/532.2 "
        "(KHTML, like Gecko) Version/1.0 Safari/532.2 Pre/1.1",
    ],
    ids=["blackberry", "opera_mini", "windows_phone", "webos"],
)
def test_is_mobile_returns_true_for_legacy_mobile_clients(ua: str) -> None:
    """Legacy mobile clients (BlackBerry, Opera Mini, Windows Phone, webOS).

    Each legacy branch in the regex has its own anchor token. If any
    stops matching because of a regex change, this parametrised test
    catches it without enumerating 4 separate tests.
    """
    assert is_mobile(ua) is True
