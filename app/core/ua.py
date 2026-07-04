"""User-Agent based device detection.

Server-side, deterministic, no JavaScript. Used by the
``UADetectionMiddleware`` (see :mod:`app.core.middleware`) to set
``request.state.is_mobile`` so route handlers and templates can
opt into device-specific rendering.

UA-based template selection is an intentional architectural
decision: see engram observation ``#15705`` (UA-based templates).
The trade-off vs. CSS media queries / responsive design is that we
serve a different Django template set on the server, not the same
DOM with different CSS. Slice A only puts the detector in place;
slice B will mint ``base_mobile.html`` and migrate templates.

Tablet handling is kept simple for v1 — iPad and Android tablets
are treated as DESKTOP (they have the screen real estate, and the
desktop template is the conservative starting point for tablet
PCs). A future slice can introduce a third state ``is_tablet``
when product needs a tablet-specific layout.
"""

from __future__ import annotations

import re

# Mobile phones User-Agent patterns. Anchored on tokens that are
# stable across browser version bumps:
#
# - ``Mobile``             → Android phones, iPhone (iOS Safari),
#                            Windows Phone (legacy), BlackBerry.
# - ``iPhone``             → iOS phones (covers UAs where Apple
#                            dropped the literal "Mobile" token).
# - ``iPod``               → iOS touch (legacy, sold until 2022).
# - ``BlackBerry``         → legacy BB handsets.
# - ``Opera\s+Mini``       → legacy Opera's proxy-rendered mode.
# - ``IEMobile``           → legacy IE mobile.
# - ``Windows\s+Phone``    → legacy Windows Phone.
# - ``webOS``              → legacy Palm / LG TVs.
# - ``Android.*Mobile``    → Android phones explicitly. The bare
#                            ``Android`` token matches tablets too
#                            (e.g. "Linux; Android 9; SM-T720"), so
#                            the ``.*Mobile`` qualifier is essential
#                            to keep them out of this branch.
#
# Verbose + IGNORECASE so the pattern stays readable and tolerates
# the (historical) Android browser / Chrome mix-up case where the
# UA is partly upper-cased by intermediaries.
_MOBILE_UA_PATTERN = re.compile(
    r"""
    Mobile
    | iPhone
    | iPod
    | BlackBerry
    | Opera\s+Mini
    | IEMobile
    | Windows\s+Phone
    | webOS
    | Android.*Mobile
    """,
    re.VERBOSE | re.IGNORECASE,
)


# Tablet UAs that incidentally contain the ``Mobile`` token. iPad is
# the canonical case (iOS Safari ALWAYS appends ``Mobile/<build>`` in
# its UA — even for iPad — because the underlying WebKit build line
# is shared with iPhone). Without checking for the iPad marker FIRST,
# the ``Mobile`` branch below would misclassify iPad as a phone.
#
# Kindle and Silk (Amazon Fire tablets / e-readers / Echo Show) are
# also in this bucket — they sometimes append ``Mobile/Safari/...``
# style strings and need a dedicated tablet marker to override.
#
# Note: Android tablets are intentionally NOT included here. Real
# Android tablets (e.g. ``Linux; Android 9; SM-T720``) omit the
# ``Mobile`` token entirely, so they fail to match the mobile pattern
# below and naturally classify as desktop. An earlier draft used a
# negative-lookahead ``Android(?!.*Mobile)`` for defense-in-depth, but
# that clause produced a false negative for legitimate mobile browsers
# on Android that strip the ``Mobile`` token (e.g. Opera Mini reports
# ``Opera/9.80 (Android; Opera Mini/...)`` without ``Mobile`` because
# its UA is server-rendered). The simpler tab set below keeps the
# classification correct for iPad/Kindle/Silk AND lets mobile-optimised
# Android browsers render the mobile template.
_TABLET_UA_PATTERN = re.compile(
    r"iPad|Kindle|Silk",
    re.IGNORECASE,
)


def is_mobile(user_agent: str | None) -> bool:
    """Return ``True`` if the User-Agent is a mobile phone.

    Args:
        user_agent: The ``User-Agent`` header value, or ``None`` for
            non-browser clients (curl, server-to-server scripts,
            health probes). Empty strings are treated as missing.

    Returns:
        ``True`` for phones (iPhone, Android phones, legacy phones),
        ``False`` for tablets (iPad, Android tablets, Kindle, Silk)
        and desktop. The check is default-deny: a missing UA is
        treated as desktop, never as mobile.

    Notes:
        Tablet identification comes first because iPad UAs include
        the literal substring ``Mobile`` (it is part of the iOS
        version string) — without the explicit exclusion, iPads
        would be misclassified as phones.
    """
    if not user_agent:
        return False
    if _TABLET_UA_PATTERN.search(user_agent):
        return False
    return bool(_MOBILE_UA_PATTERN.search(user_agent))
