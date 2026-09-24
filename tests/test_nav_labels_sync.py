"""Pin the nav labels used by the E2E suite against the single source of truth.

Why this test exists (gap found on 2026-09-22)
---------------------------------------------

PR #848 (issue #806) renamed three long nav labels ("Entradas en lote"
→ "Lote", "Casas de acogida" → "Casas", "Estancias de acogida" →
"Estancias") in ``app/core/nav.py`` and both base templates, but it did
not update ``tests/e2e/test_nav_active_state.py``, which carries its own
hardcoded ``EXPECTED_ACTIVE_LABEL`` map.

Nothing caught the drift because the ``e2e`` CI job only runs on
``workflow_dispatch`` and tag pushes (see ``.github/workflows/ci.yml``),
and even when it runs, ``_skip_if_redirected`` skips every authenticated
route when there is no session — which is always the case, since the
suite has no login fixture. In practice only one atom of that file
(``test_no_active_state_on_login_route``) ever executes.

This test closes the loop from the unit suite, which *does* run on every
PR: it reads the E2E module's ``EXPECTED_ACTIVE_LABEL`` literal via
``ast`` (no ``playwright`` import needed) and asserts it agrees with
``app.core.nav.NAV_ITEMS``. A future rename that forgets the E2E map now
fails the build instead of rotting silently.

It also pins the long-form labels that the rename moved into the
``title=`` attribute of the desktop template, so the hover tooltip
cannot silently diverge from the short label either.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.core.nav import NAV_ITEMS

REPO_ROOT = Path(__file__).resolve().parents[1]
E2E_FILE = REPO_ROOT / "tests" / "e2e" / "test_nav_active_state.py"
BASE_TEMPLATE = REPO_ROOT / "app" / "templates" / "base.html"

# The long form each short label replaced (issue #806). Pinned so the
# ``title=`` tooltip on the desktop template keeps carrying the
# descriptive wording the short label dropped.
LONG_FORM_TITLES: dict[str, str] = {
    "/entradas/batch/new": "Entradas en lote",
    "/casas-acogida": "Casas de acogida",
    "/acogidas": "Estancias de acogida",
}


def _load_expected_active_label() -> dict[str, str]:
    """Extract the ``EXPECTED_ACTIVE_LABEL`` literal from the E2E module.

    Parsed with ``ast`` rather than imported so this atom does not
    depend on ``playwright`` being installed (the E2E module imports it
    at top level, and ``tests/test_*.py`` must stay runnable in the
    minimal CI image).
    """
    tree = ast.parse(E2E_FILE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id == "EXPECTED_ACTIVE_LABEL"
                for target in node.targets
            )
        ):
            value = ast.literal_eval(node.value)
            assert isinstance(value, dict)
            return value
    raise AssertionError(
        f"EXPECTED_ACTIVE_LABEL not found in {E2E_FILE.relative_to(REPO_ROOT)}"
    )


def test_e2e_expected_labels_match_nav_items() -> None:
    """Every ``NAV_ITEMS`` entry has the same label the E2E suite expects.

    ``NAV_ITEMS`` is the source of truth for both base templates; the E2E
    map is a hand-maintained copy. When they disagree, the E2E suite is
    asserting against labels that can never appear on the page.
    """
    expected = _load_expected_active_label()
    nav_labels = {item.href: item.label for item in NAV_ITEMS}

    assert nav_labels, "NAV_ITEMS must not be empty"

    for href, label in sorted(nav_labels.items()):
        assert href in expected, (
            f"nav href {href!r} (label {label!r}) is missing from the E2E "
            f"EXPECTED_ACTIVE_LABEL map in "
            f"{E2E_FILE.relative_to(REPO_ROOT)}; add it there too."
        )
        assert expected[href] == label, (
            f"label drift for {href!r}: app/core/nav.py says {label!r} but "
            f"the E2E map says {expected[href]!r}. Update "
            f"{E2E_FILE.relative_to(REPO_ROOT)} to match."
        )


def test_e2e_map_has_no_stale_entries() -> None:
    """The E2E map carries no href the nav no longer renders."""
    expected = _load_expected_active_label()
    nav_hrefs = {item.href for item in NAV_ITEMS}

    stale = sorted(set(expected) - nav_hrefs)
    assert not stale, (
        f"EXPECTED_ACTIVE_LABEL has entries for hrefs absent from "
        f"app/core/nav.py::NAV_ITEMS: {stale}. Remove them."
    )


def test_desktop_template_keeps_long_form_titles() -> None:
    """The desktop nav carries the long-form ``title=`` for renamed items.

    Issue #806 shortened three labels; the descriptive wording moved to
    the ``title=`` attribute so the tooltip still explains what "Lote"
    and friends mean. Since #808 the anchors are rendered by a single
    Jinja loop, so the long form lives on ``NavItem.title`` (the source
    of truth, pinned here against ``LONG_FORM_TITLES``) and the desktop
    template renders it via ``title="{{ item.title }}"``. The mobile
    template intentionally omits the attribute (no hover on touch
    devices) — both templates are pinned here on that split.
    """
    nav_titles = {item.href: item.title for item in NAV_ITEMS}
    desktop = BASE_TEMPLATE.read_text(encoding="utf-8")
    mobile = (REPO_ROOT / "app" / "templates" / "base_mobile.html").read_text(
        encoding="utf-8"
    )

    for href, long_form in sorted(LONG_FORM_TITLES.items()):
        assert nav_titles.get(href) == long_form, (
            f"title drift for {href!r}: expected {long_form!r} on "
            f"NavItem.title, got {nav_titles.get(href)!r}."
        )

    assert 'title="{{ item.title }}"' in desktop, (
        "desktop template must render the long-form tooltip via the nav "
        f"loop's title attribute; not found in "
        f"{BASE_TEMPLATE.relative_to(REPO_ROOT)}."
    )
    assert 'title="{{ item.title }}"' not in mobile, (
        "mobile template must not render title= attributes (no hover on "
        "touch devices)."
    )
