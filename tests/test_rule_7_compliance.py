"""Regression test for AGENTS.md Rule 7: redirects must not use HTTPException.

This is a characterization test. It pins the CURRENT good behavior of
``app.core.auth_dependencies.require_authorized_user``: the function
returns a ``RedirectResponse`` for both the no-session and not-authorized
branches, never ``raise HTTPException(status_code=302, ...)``.

History
-------
Rule 7 of the code-quality rules (AGENTS.md:275-289) mandates
``RedirectResponse`` for control-flow redirects and reserves
``HTTPException`` for real HTTP error conditions (4xx/5xx). The
``hardening-2026-q2`` Slice 5 audit at
``docs/audits/auth-dependencies-audit-2026-Q2.md`` confirmed the
function is currently compliant; this test makes that compliance
fail-loud if a future regression reintroduces the bad pattern.

Why ``inspect.getsource`` and not a behavioural test
---------------------------------------------------
A behavioural test would assert "POST without auth returns 302 to /login",
which is already covered by ``test_auth_dependencies.py::test_pre_fix_cookie_redirects_to_unauthorized``
and the redirect-route tests. What those tests do NOT catch is the
specific textual pattern ``HTTPException(status_code=302, ...)`` if a
future developer wraps the redirect in an exception to satisfy a
flaky lint rule. ``inspect.getsource`` reads the function's source
verbatim and matches the exact anti-pattern string.

Known limitation
----------------
If a future PR introduces an alternative redirect pattern that
technically complies with Rule 7 (e.g.
``Response(status_code=302, headers={"location": "/login"})``) but is
also written as a ``raise``, this test will still fail because the
literal substring ``HTTPException(status_code=302`` is absent from
``inspect.getsource`` — only the exact anti-pattern string is checked.
The lint rule APAP002 (out of scope for Slice 5, see spec §Out of scope)
would close this gap with AST-level detection.
"""

from __future__ import annotations

import inspect

import pytest


def _require_authorized_user_source() -> str:
    """Return the auth guard and redirect-helper source."""
    from app.core.auth_dependencies import require_authorized_user
    from app.core.di.auth_dependencies_session_di import _deny

    return inspect.getsource(require_authorized_user) + inspect.getsource(_deny)


def test_uses_redirectresponse_not_http_exception_in_require_authorized_user() -> None:
    """Rule 7: ``require_authorized_user`` MUST NOT contain ``HTTPException(status_code=302``.

    Static source check on the function body. If a future PR reverts
    the redirect to ``raise HTTPException(status_code=302, ...)``,
    this test fails and the PR cannot merge.
    """
    source = _require_authorized_user_source()
    assert "HTTPException(status_code=302" not in source, (
        "Rule 7 violation: require_authorized_user uses HTTPException for a "
        "redirect. Use RedirectResponse instead (AGENTS.md:275-289). "
        "See docs/audits/auth-dependencies-audit-2026-Q2.md (F-1 mitigation)."
    )


def test_require_authorized_user_uses_redirect_response() -> None:
    """Positive companion: ``require_authorized_user`` MUST use RedirectResponse.

    Counterpart to the negative check above. Catches the inverse
    regression where the redirect is accidentally replaced by a bare
    ``return None`` or ``raise HTTPException(...)`` with a different
    status code.
    """
    source = _require_authorized_user_source()
    assert "RedirectResponse" in source, (
        "Rule 7 compliance signal missing: require_authorized_user no longer "
        "returns RedirectResponse. The auth guard must redirect unauthenticated "
        "or unauthorized callers to /login or /unauthorized respectively."
    )


@pytest.mark.parametrize(
    "anti_pattern",
    [
        "HTTPException(status_code=302",
        "raise HTTPException(302",
        "raise HTTPException(status_code=302",
    ],
)
def test_no_redirect_as_http_exception_anti_patterns(anti_pattern: str) -> None:
    """Parametrized sweep of known anti-patterns in the auth guard body.

    Belt-and-braces: catches common reformulations a developer might
    try when refactoring (different spacing, parens placement).
    """
    source = _require_authorized_user_source()
    assert anti_pattern not in source, (
        f"Rule 7 violation: require_authorized_user contains '{anti_pattern}'. "
        "Redirects must use RedirectResponse, not HTTPException. See "
        "docs/audits/auth-dependencies-audit-2026-Q2.md and AGENTS.md Rule 7."
    )


def test_auth_dependencies_module_has_no_redirect_http_exception() -> None:
    """Module-level guard: no function in ``auth_dependencies.py`` uses HTTPException for redirects.

    Broader than the function-level check: catches a future helper
    (e.g. a new ``require_admin_user``) that re-introduces the
    anti-pattern.
    """
    import app.core.auth_dependencies as mod

    module_source = inspect.getsource(mod)
    assert "HTTPException(status_code=302" not in module_source, (
        "Rule 7 violation: app/core/auth_dependencies.py contains "
        "HTTPException(status_code=302). All redirects in this module "
        "must use RedirectResponse. See AGENTS.md:275-289."
    )
